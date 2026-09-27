import AppKit
import Charts
import SwiftUI

struct CurvePoint: Codable, Equatable {
    var temperature: Double
    var fraction: Double
}
struct CurveSettings: Codable, Equatable {
    var baselineRPM: Double
    var curve: [CurvePoint]
    var palmCurve: [CurvePoint]
    var error: String? {
        guard baselineRPM.isFinite, (1200...2500).contains(baselineRPM) else {
            return "Baseline must be between 1,200 and 2,500 RPM."
        }
        for points in [curve, palmCurve] {
            guard (2...20).contains(points.count), points.last?.fraction == 1,
                  points.allSatisfy({ $0.temperature.isFinite && (10...90).contains($0.temperature) &&
                      $0.fraction.isFinite && (0...1).contains($0.fraction) }) else {
                return "Use 2–20 points, temperatures from 10 to 90°C, and finish at 100% demand."
            }
            guard zip(points, points.dropFirst()).allSatisfy({ $0.temperature < $1.temperature && $0.fraction <= $1.fraction }) else {
                return "Temperatures must increase and fan demand cannot decrease."
            }
        }
        return nil
    }
}
struct FanLimit: Decodable { let minimum: Double; let maximum: Double }
struct EditorData: Decodable {
    let current: CurveSettings
    let saved: CurveSettings?
    let presets: [String: CurveSettings]
    let limits: [FanLimit]
}
struct ActionResult: Decodable { let ok: Bool; let message: String }
struct Reading: Decodable { let cpu: Double?; let gpu: Double?; let palm: Double?; let time: String? }

final class EditorModel: ObservableObject {
    @Published var data: EditorData?
    @Published var draft: CurveSettings?
    @Published var message = "Loading…"
    @Published var busy = true
    @Published var reading: Reading?
    private var clock: Timer?
    private let plugin = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/SwiftBar/Plugins/cooler.5s.py")

    init() {
        refreshReading()
        clock = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.refreshReading() }
    }

    // Cooler's status file is world-readable; a reading older than ten seconds is not "now".
    func refreshReading() {
        let url = URL(fileURLWithPath: "/Library/Application Support/Cooler/status.json")
        guard let bytes = try? Data(contentsOf: url), let value = try? JSONDecoder().decode(Reading.self, from: bytes),
              let stamp = value.time, let time = ISO8601DateFormatter().date(from: stamp),
              abs(time.timeIntervalSinceNow) <= 10 else { reading = nil; return }
        reading = value
    }

    func run(_ arguments: [String]) throws -> Data {
        let process = Process(), output = Pipe(), errors = Pipe()
        process.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/python3")
        process.arguments = [plugin.path] + arguments
        process.standardOutput = output
        process.standardError = errors
        try process.run()
        let result = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let response = try? JSONDecoder().decode(ActionResult.self, from: result)
            throw NSError(domain: "Cooler", code: 1, userInfo: [NSLocalizedDescriptionKey:
                response?.message ?? "Could not read Cooler. Check its SwiftBar status and try again."])
        }
        return result
    }

    func load() {
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let data = try JSONDecoder().decode(EditorData.self, from: self.run(["--editor-data"]))
                guard data.limits.count == 2 else { throw CocoaError(.coderReadCorrupt) }
                DispatchQueue.main.async {
                    self.data = data
                    // Max is a mode; start editing a useful normal curve instead of a flat maximum.
                    self.draft = data.current.curve.allSatisfy { $0.fraction == 1 }
                        ? (data.saved ?? data.presets["cooler"]!) : data.current
                    self.busy = false
                    self.message = ""
                }
            } catch {
                DispatchQueue.main.async { self.busy = false; self.message = error.localizedDescription }
            }
        }
    }

    func apply() {
        guard let draft, draft.error == nil, !busy else { return }
        busy = true
        message = "Waiting for authorization…"
        DispatchQueue.global(qos: .userInitiated).async {
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("cooler-edit-\(UUID().uuidString).json")
            defer { try? FileManager.default.removeItem(at: file) }
            do {
                try JSONEncoder().encode(draft).write(to: file, options: .atomic)
                let result = try JSONDecoder().decode(ActionResult.self, from: self.run(["--apply-custom", file.path]))
                DispatchQueue.main.async {
                    self.message = result.ok ? "" : result.message
                    self.busy = false
                    if result.ok, let data = self.data {
                        self.data = EditorData(current: draft, saved: draft, presets: data.presets, limits: data.limits)
                    }
                }
            } catch {
                DispatchQueue.main.async { self.message = error.localizedDescription; self.busy = false }
            }
        }
    }
}

// The controller interpolates linearly and holds the end values beyond the first and last points.
func demand(at temperature: Double, on points: [CurvePoint]) -> Double {
    guard let first = points.first, let last = points.last else { return 0 }
    if temperature <= first.temperature { return first.fraction }
    for (a, b) in zip(points, points.dropFirst()) where temperature <= b.temperature {
        return a.fraction + (b.fraction - a.fraction) * (temperature - a.temperature) / (b.temperature - a.temperature)
    }
    return last.fraction
}

struct CurveChart: View {
    @Binding var points: [CurvePoint]
    @Binding var selection: Int?
    let palm: Bool
    let now: Double?
    let insert: (Double) -> Void
    @State private var dragging: Int?
    @State private var frozen: ClosedRange<Double>?

    private var domain: ClosedRange<Double> {
        if let frozen { return frozen }
        let low = min(palm ? 25 : 35, (points.first?.temperature ?? 40) - 5)
        let high = max(palm ? 45 : 90, (points.last?.temperature ?? 85) + 5)
        return (low / 5).rounded(.down) * 5...(high / 5).rounded(.up) * 5
    }

    // Keeps temperatures increasing, demand non-decreasing, and the last point at full speed.
    private func move(_ index: Int, to temperature: Double, fraction: Double) {
        guard points.indices.contains(index) else { return }
        let lowT = index == 0 ? 10 : points[index - 1].temperature.nextUp
        let highT = index == points.count - 1 ? 90 : points[index + 1].temperature.nextDown
        points[index].temperature = min(highT, max(lowT, temperature.rounded()))
        if index < points.count - 1 {
            let lowF = index == 0 ? 0 : points[index - 1].fraction
            points[index].fraction = min(points[index + 1].fraction, max(lowF, (fraction * 100).rounded() / 100))
        }
    }

    private func nearest(to location: CGPoint, proxy: ChartProxy, plot: CGRect) -> Int? {
        var best: (index: Int, distance: CGFloat)?
        for index in points.indices {
            guard let x = proxy.position(forX: points[index].temperature),
                  let y = proxy.position(forY: points[index].fraction * 100) else { continue }
            let distance = hypot(plot.minX + x - location.x, plot.minY + y - location.y)
            if distance < 18, distance < (best?.distance ?? .infinity) { best = (index, distance) }
        }
        return best?.index
    }

    var body: some View {
        let range = domain
        let line = [CurvePoint(temperature: range.lowerBound, fraction: points.first?.fraction ?? 0)] + points
            + [CurvePoint(temperature: range.upperBound, fraction: points.last?.fraction ?? 1)]
        Chart {
            ForEach(Array(line.enumerated()), id: \.offset) { _, point in
                AreaMark(x: .value("Temperature", point.temperature), y: .value("Speed", point.fraction * 100))
                    .foregroundStyle(.linearGradient(colors: [Color.accentColor.opacity(0.24), Color.accentColor.opacity(0.03)],
                                                     startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("Temperature", point.temperature), y: .value("Speed", point.fraction * 100))
                    .foregroundStyle(Color.accentColor)
                    .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
            }
            if let now, range.contains(now) {
                RuleMark(x: .value("Now", now))
                    .foregroundStyle(Color.secondary.opacity(0.7))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    .annotation(position: .top, spacing: 2) {
                        Text("\(Int(now.rounded()))°").font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                    }
                PointMark(x: .value("Now", now), y: .value("Speed", demand(at: now, on: points) * 100))
                    .symbolSize(30).foregroundStyle(Color.secondary)
            }
            ForEach(points.indices, id: \.self) { index in
                PointMark(x: .value("Temperature", points[index].temperature), y: .value("Speed", points[index].fraction * 100))
                    .symbol {
                        Circle()
                            .fill(selection == index ? Color.accentColor : Color(nsColor: .controlBackgroundColor))
                            .overlay(Circle().strokeBorder(Color.accentColor, lineWidth: 2))
                            .frame(width: selection == index ? 14 : 11, height: selection == index ? 14 : 11)
                    }
            }
        }
        .chartXScale(domain: range)
        .chartYScale(domain: -4...104)
        .chartXAxis {
            AxisMarks(values: .stride(by: palm ? 5 : 10)) { value in
                AxisGridLine()
                AxisValueLabel { if let t = value.as(Double.self) { Text("\(Int(t))°") } }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: [0, 50, 100]) { value in
                AxisGridLine()
                AxisValueLabel { if let v = value.as(Double.self) { Text(v == 0 ? "Min" : v == 100 ? "Full" : "50%") } }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 0)
                        .onChanged { event in
                            guard let anchor = proxy.plotFrame else { return }
                            let plot = geometry[anchor]
                            if dragging == nil {
                                frozen = range
                                dragging = nearest(to: event.startLocation, proxy: proxy, plot: plot)
                                if let dragging { selection = dragging }
                            }
                            guard let index = dragging,
                                  let temperature: Double = proxy.value(atX: event.location.x - plot.minX),
                                  let speed: Double = proxy.value(atY: event.location.y - plot.minY) else { return }
                            if event.translation != .zero { move(index, to: temperature, fraction: speed / 100) }
                        }
                        .onEnded { _ in dragging = nil; frozen = nil })
                    .simultaneousGesture(SpatialTapGesture(count: 2).onEnded { event in
                        guard let anchor = proxy.plotFrame,
                              let temperature: Double = proxy.value(atX: event.location.x - geometry[anchor].minX) else { return }
                        insert(temperature)
                    })
            }
        }
        .accessibilityLabel(palm ? "Palm rest curve" : "CPU and GPU curve")
        .accessibilityValue("\(points.count) points")
    }
}

struct EditorView: View {
    @StateObject private var model = EditorModel()
    @State private var palm = false
    @State private var selection: Int? = 0
    private var settings: Binding<CurveSettings> {
        Binding(get: { model.draft! }, set: {
            model.draft = $0
            model.message = ""
        })
    }
    private var points: Binding<[CurvePoint]> { palm ? settings.palmCurve : settings.curve }
    private func commitFields() { NSApp.keyWindow?.makeFirstResponder(nil) }
    private var now: Double? {
        guard let reading = model.reading else { return nil }
        return palm ? reading.palm : [reading.cpu, reading.gpu].compactMap { $0 }.max()
    }
    private var status: String {
        if let error = model.draft?.error { return error }
        if !model.message.isEmpty { return model.message }
        guard let draft = model.draft, let data = model.data else { return "" }
        return draft == data.current ? "Active" : "Not applied"
    }

    var body: some View {
        Group {
            if model.draft != nil, let data = model.data {
                editor(data).disabled(model.busy)
            } else {
                VStack(spacing: 12) {
                    if model.busy { ProgressView() } else {
                        Text(model.message).foregroundStyle(.secondary)
                        Button("Try again") { model.load() }
                    }
                }.frame(width: 640, height: 300)
            }
        }
        .navigationTitle("Custom Curve")
        .navigationSubtitle(status)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Picker("Curve", selection: $palm) {
                    Text("CPU & GPU").tag(false)
                    Text("Palm rest").tag(true)
                }.pickerStyle(.segmented).labelsHidden().fixedSize()
            }
            ToolbarItemGroup(placement: .primaryAction) {
                if let data = model.data {
                    Menu("Presets") {
                        Button("Installed curve") { use(data.current) }
                        if let saved = data.saved { Button("Saved Custom curve") { use(saved) } }
                        Divider()
                        ForEach(["quiet", "balanced", "cooler"], id: \.self) { name in
                            Button(name.capitalized) { use(data.presets[name]!) }
                        }
                    }.disabled(model.busy)
                    Button("Apply") {
                        commitFields()
                        DispatchQueue.main.async { model.apply() }
                    }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                    // Blue only when there is something to apply.
                    .tint(model.draft == data.current ? Color.secondary : Color.accentColor)
                    .disabled(model.busy || model.draft?.error != nil || model.draft == data.current)
                }
            }
        }
        .onAppear { model.load() }
        .onChange(of: palm) { selection = 0 }
    }

    private func use(_ curve: CurveSettings) {
        commitFields()
        settings.wrappedValue = curve
        selection = 0
    }

    private func editor(_ data: EditorData) -> some View {
        // Everything below keeps the curve it was made for, so a tab switch can't redirect an edit.
        let curve = points
        let count = curve.wrappedValue.count
        let removable = selection.map { $0 < count - 1 } ?? false && count > 2
        return VStack(spacing: 12) {
            CurveChart(points: curve, selection: $selection, palm: palm, now: now) { insert($0, in: curve) }
                .frame(height: 230)
            HStack(spacing: 14) {
                ControlGroup {
                    Button { add(to: curve) } label: { Image(systemName: "plus") }
                        .help("Add point").disabled(count >= 20)
                    Button { remove(from: curve) } label: { Image(systemName: "minus") }
                        .help("Remove point").disabled(!removable)
                }.fixedSize()
                if let index = selection, index < count {
                    pointFields(index, in: curve, limits: data.limits)
                }
                Spacer(minLength: 12)
                Text("Minimum").foregroundStyle(.secondary)
                TextField("Minimum RPM", value: baseline, format: .number.precision(.fractionLength(0)))
                    .textFieldStyle(.roundedBorder).frame(width: 58).multilineTextAlignment(.trailing)
                    .accessibilityLabel("Baseline RPM")
                Text("RPM").foregroundStyle(.secondary)
                Stepper("Minimum RPM", value: baseline, in: 1200...2500, step: 100).labelsHidden()
            }
        }
        .padding(16)
        .frame(width: 640)
    }

    private var baseline: Binding<Double> {
        Binding(get: { settings.wrappedValue.baselineRPM },
                set: { settings.wrappedValue.baselineRPM = min(2500, max(1200, $0.rounded())) })
    }

    // Adds a point in the widest gap and selects it.
    private func add(to curve: Binding<[CurvePoint]>) {
        commitFields()
        let p = curve.wrappedValue
        guard p.count < 20, let i = (0..<(p.count - 1)).max(by: {
            p[$0 + 1].temperature - p[$0].temperature < p[$1 + 1].temperature - p[$1].temperature }) else { return }
        curve.wrappedValue.insert(CurvePoint(temperature: ((p[i].temperature + p[i + 1].temperature) / 2).rounded(),
                                             fraction: (p[i].fraction + p[i + 1].fraction) / 2), at: i + 1)
        selection = i + 1
    }

    // Double-click on the graph: a new point on the curve at that temperature.
    private func insert(_ temperature: Double, in curve: Binding<[CurvePoint]>) {
        let p = curve.wrappedValue, t = temperature.rounded()
        guard p.count < 20, t >= 10, let index = p.firstIndex(where: { $0.temperature > t }),
              index == 0 || p[index - 1].temperature < t else { return }
        commitFields()
        curve.wrappedValue.insert(CurvePoint(temperature: t, fraction: (demand(at: t, on: p) * 100).rounded() / 100), at: index)
        selection = index
    }

    private func remove(from curve: Binding<[CurvePoint]>) {
        commitFields()
        guard let index = selection, index < curve.wrappedValue.count - 1, curve.wrappedValue.count > 2 else { return }
        curve.wrappedValue.remove(at: index)
        selection = max(0, index - 1)
    }

    // The selected point's exact values. Typed values are held between the neighbors, like dragging.
    private func pointFields(_ index: Int, in curve: Binding<[CurvePoint]>, limits: [FanLimit]) -> some View {
        let p = curve.wrappedValue
        let last = index >= p.count - 1
        let temperature = Binding<Double>(
            get: { index < curve.wrappedValue.count ? curve.wrappedValue[index].temperature : 0 },
            set: { value in
                let q = curve.wrappedValue
                guard index < q.count else { return }
                let low = index == 0 ? 10 : q[index - 1].temperature.nextUp
                let high = index == q.count - 1 ? 90 : q[index + 1].temperature.nextDown
                curve.wrappedValue[index].temperature = min(high, max(low, value))
            })
        let speed = Binding<Double>(
            get: { index < curve.wrappedValue.count ? curve.wrappedValue[index].fraction * 100 : 0 },
            set: { value in
                let q = curve.wrappedValue
                guard index < q.count - 1 else { return }
                let low = index == 0 ? 0 : q[index - 1].fraction
                curve.wrappedValue[index].fraction = min(q[index + 1].fraction, max(low, value / 100))
            })
        let fraction = index < p.count ? p[index].fraction : 0
        let rpm = limits.map { limit -> String in
            let floor = max(settings.wrappedValue.baselineRPM, limit.minimum)
            let value = floor + (limit.maximum - floor) * fraction
            return value.isFinite ? value.formatted(.number.precision(.fractionLength(0))) : "?"
        }.joined(separator: " / ")
        return HStack(spacing: 5) {
            TextField("Temperature", value: temperature, format: .number.precision(.fractionLength(0...1)))
                .textFieldStyle(.roundedBorder).frame(width: 44).multilineTextAlignment(.trailing)
                .accessibilityLabel("Selected point temperature")
            Text("°C").foregroundStyle(.secondary)
            TextField("Speed", value: speed, format: .number.precision(.fractionLength(0)))
                .textFieldStyle(.roundedBorder).frame(width: 40).multilineTextAlignment(.trailing)
                .disabled(last).accessibilityLabel("Selected point speed")
            Text("%").foregroundStyle(.secondary)
            Text("\(rpm) RPM").foregroundStyle(.secondary).monospacedDigit().padding(.leading, 6)
        }
    }
}

@main struct CoolerCurvesApp: App {
    var body: some Scene {
        Window("Custom Curve", id: "curves") { EditorView() }
            .windowResizability(.contentSize)
    }
}
