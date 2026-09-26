import AppKit
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

final class EditorModel: ObservableObject {
    @Published var data: EditorData?
    @Published var draft: CurveSettings?
    @Published var message = "Reading installed curves and fan limits…"
    @Published var busy = true
    @Published var succeeded = false
    private let plugin = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/SwiftBar/Plugins/cooler.5s.py")

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
                    self.message = "Changes stay in this window until you apply them."
                }
            } catch {
                DispatchQueue.main.async { self.busy = false; self.message = error.localizedDescription }
            }
        }
    }

    func apply() {
        guard let draft, draft.error == nil, !busy else { return }
        busy = true
        succeeded = false
        message = "Waiting for macOS authorization…"
        DispatchQueue.global(qos: .userInitiated).async {
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("cooler-edit-\(UUID().uuidString).json")
            defer { try? FileManager.default.removeItem(at: file) }
            do {
                try JSONEncoder().encode(draft).write(to: file, options: .atomic)
                let result = try JSONDecoder().decode(ActionResult.self, from: self.run(["--apply-custom", file.path]))
                DispatchQueue.main.async {
                    self.message = result.message
                    self.succeeded = result.ok
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

struct CurveGraph: View {
    @Binding var points: [CurvePoint]
    let baseline: Double
    let limits: [FanLimit]
    let palm: Bool
    @State private var dragRange: ClosedRange<Double>?
    private var range: ClosedRange<Double> {
        dragRange ?? min(palm ? 25 : 40, (points.first?.temperature ?? 40) - 5)...max(palm ? 45 : 90, (points.last?.temperature ?? 85) + 5)
    }
    private func rpm(_ fraction: Double, _ fan: Int) -> Double {
        let floor = max(baseline, limits[fan].minimum)
        return floor + (limits[fan].maximum - floor) * fraction
    }
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width - 76
            let height = geometry.size.height - 44
            let lower = range.lowerBound, upper = range.upperBound
            let x: (Double) -> Double = { 54 + ($0 - lower) / (upper - lower) * width }
            let y: (Double) -> Double = { 14 + height * (1 - $0 / 7000) }
            ZStack(alignment: .topLeading) {
                ForEach([2000, 4000, 6000], id: \.self) { value in
                    Path { p in p.move(to: CGPoint(x: 54, y: y(Double(value)))); p.addLine(to: CGPoint(x: 54 + width, y: y(Double(value)))) }
                        .stroke(Color.secondary.opacity(0.2), lineWidth: 1)
                    Text(value.formatted()).font(.caption).foregroundStyle(.secondary)
                        .position(x: 24, y: y(Double(value)))
                }
                Text("RPM").font(.caption2).foregroundStyle(.secondary).position(x: 24, y: 6)
                ForEach(0..<6) { tick in
                    let t = lower + Double(tick) * (upper - lower) / 5
                    Text("\(Int(t.rounded()))°C").font(.caption).foregroundStyle(.secondary).position(x: x(t), y: height + 34)
                }
                ForEach(0..<2) { fan in
                    Path { path in
                        guard let first = points.first, let last = points.last else { return }
                        path.move(to: CGPoint(x: x(lower), y: y(rpm(first.fraction, fan))))
                        for point in points { path.addLine(to: CGPoint(x: x(point.temperature), y: y(rpm(point.fraction, fan)))) }
                        path.addLine(to: CGPoint(x: x(upper), y: y(rpm(last.fraction, fan))))
                    }
                    .stroke(fan == 0 ? Color.accentColor : Color.secondary, style: StrokeStyle(lineWidth: 2, dash: fan == 0 ? [] : [6, 4]))
                }
                ForEach(points.indices, id: \.self) { index in
                    Circle().fill(Color.accentColor).frame(width: 11, height: 11)
                        .frame(width: 28, height: 28).contentShape(Rectangle())
                        .position(x: x(points[index].temperature), y: y(rpm(points[index].fraction, 0)))
                        .gesture(DragGesture(minimumDistance: 0, coordinateSpace: .named("graph"))
                            .onChanged { event in
                                if dragRange == nil { dragRange = lower...upper }
                                let t = lower + (event.location.x - 54) / width * (upper - lower)
                                let floor = max(baseline, limits[0].minimum)
                                let f = ((1 - (event.location.y - 14) / height) * 7000 - floor) / (limits[0].maximum - floor)
                                let lowT = index == 0 ? 10 : points[index - 1].temperature.nextUp
                                let highT = index == points.count - 1 ? 90 : points[index + 1].temperature.nextDown
                                points[index].temperature = min(highT, max(lowT, t.rounded()))
                                if index != points.count - 1 {
                                    let lowF = index == 0 ? 0 : points[index - 1].fraction
                                    points[index].fraction = min(points[index + 1].fraction, max(lowF, (f * 100).rounded() / 100))
                                }
                            }.onEnded { _ in dragRange = nil })
                        .help("Drag to change temperature and fan demand. Exact values are below.")
                        .accessibilityLabel("Curve point \(index + 1)")
                }
            }.coordinateSpace(name: "graph")
        }
        .frame(height: 224)
    }
}

struct EditorView: View {
    @StateObject private var model = EditorModel()
    @State private var palm = false
    private var settings: Binding<CurveSettings> {
        Binding(get: { model.draft! }, set: {
            model.draft = $0
            model.succeeded = false
            model.message = "Unapplied changes. Save & apply to use this curve."
        })
    }
    private var points: Binding<[CurvePoint]> { palm ? settings.palmCurve : settings.curve }
    private func commitFields() { NSApp.keyWindow?.makeFirstResponder(nil) }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Cooling curves").font(.title2.weight(.semibold))
                    Text("Tune your saved Custom curve. The strongest CPU, GPU or palm-rest request wins.")
                        .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                if let data = model.data {
                    Menu("Start from") {
                        Button("Installed curve") { settings.wrappedValue = data.current }
                        if let saved = data.saved { Button("Saved Custom curve") { settings.wrappedValue = saved } }
                        Divider()
                        ForEach(["quiet", "balanced", "cooler"], id: \.self) { name in
                            Button(name.capitalized) { settings.wrappedValue = data.presets[name]! }
                        }
                    }.fixedSize().disabled(model.busy)
                }
            }
            if model.draft != nil, let data = model.data {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("Minimum airflow")
                        TextField("Baseline RPM", value: settings.baselineRPM, format: .number.precision(.fractionLength(0)))
                            .textFieldStyle(.roundedBorder).frame(width: 80).accessibilityLabel("Baseline RPM")
                        Text("RPM").foregroundStyle(.secondary)
                        Spacer()
                        Text("1,200–2,500 RPM").font(.caption).foregroundStyle(.secondary)
                    }
                    Picker("Sensor curve", selection: $palm) {
                        Text("CPU & GPU").tag(false)
                        Text("Palm rest").tag(true)
                    }.pickerStyle(.segmented)
                    HStack(spacing: 18) {
                        Label("Left fan", systemImage: "minus").foregroundStyle(Color.accentColor)
                        Label("Right fan", systemImage: "ellipsis").foregroundStyle(.secondary)
                        Spacer()
                        Text("Drag a point or edit its values below").foregroundStyle(.secondary)
                    }.font(.caption)
                    if model.draft!.error == nil {
                        CurveGraph(points: points, baseline: model.draft!.baselineRPM, limits: data.limits, palm: palm)
                    } else {
                        Text("Fix the values below to preview the curve.").foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity).frame(height: 224)
                    }
                    HStack {
                        Text("Temperature").frame(width: 105, alignment: .leading)
                        Text("Fan demand").frame(maxWidth: .infinity, alignment: .leading)
                        Text("Left / right RPM").frame(width: 150, alignment: .trailing)
                        Color.clear.frame(width: 24)
                    }.font(.caption).foregroundStyle(.secondary)
                    ScrollView {
                        VStack(spacing: 10) {
                            ForEach(points.wrappedValue.indices, id: \.self) { i in
                                pointRow(i, limits: data.limits)
                            }
                        }.padding(.trailing, 3)
                    }.frame(minHeight: 130, maxHeight: 195)
                    HStack {
                        Button("Add point") {
                            commitFields()
                            let p = points.wrappedValue
                            if let i = (0..<(p.count - 1)).max(by: { p[$0 + 1].temperature - p[$0].temperature < p[$1 + 1].temperature - p[$1].temperature }) {
                                points.wrappedValue.insert(CurvePoint(temperature: (p[i].temperature + p[i+1].temperature) / 2,
                                                                       fraction: (p[i].fraction + p[i+1].fraction) / 2), at: i+1)
                            }
                        }.disabled(points.wrappedValue.count >= 20 || model.draft!.error != nil)
                        Spacer()
                        Text("100% reaches each fan’s maximum. The last point stays at 100%.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }.disabled(model.busy)
            }
            Divider()
            HStack(alignment: .center, spacing: 16) {
                if model.busy { ProgressView().controlSize(.small) }
                Text(model.draft?.error ?? model.message)
                    .font(.callout).foregroundStyle(model.draft?.error != nil ? Color.red : Color.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("action-status")
                Spacer(minLength: 10)
                if model.data == nil {
                    Button("Try again") { model.load() }.disabled(model.busy)
                } else {
                    Button(model.succeeded ? "Applied" : "Save & apply") {
                        commitFields()
                        DispatchQueue.main.async { model.apply() }
                    }
                    .buttonStyle(.borderedProminent).keyboardShortcut(.defaultAction)
                    .disabled(model.busy || model.draft?.error != nil)
                    .accessibilityIdentifier("apply-curve")
                }
            }
        }.padding(24).frame(minWidth: 720, idealWidth: 760, minHeight: 650)
            .onAppear { model.load() }
    }

    private func pointRow(_ index: Int, limits: [FanLimit]) -> some View {
        HStack(spacing: 10) {
            HStack(spacing: 4) {
                TextField("Temperature", value: points[index].temperature, format: .number.precision(.fractionLength(0...1)))
                    .textFieldStyle(.roundedBorder).frame(width: 67)
                    .accessibilityLabel("Point \(index + 1) temperature")
                Text("°C").foregroundStyle(.secondary)
            }.frame(width: 105, alignment: .leading)
            let demand = Binding<Double>(get: { points.wrappedValue[index].fraction * 100 },
                                         set: { points.wrappedValue[index].fraction = $0 / 100 })
            Slider(value: demand, in: 0...100, step: 1)
                .disabled(index == points.wrappedValue.count - 1)
                .accessibilityLabel("Point \(index + 1) fan demand")
            TextField("Demand", value: demand, format: .number.precision(.fractionLength(0...1)))
                .textFieldStyle(.roundedBorder).frame(width: 55)
                .disabled(index == points.wrappedValue.count - 1)
                .accessibilityLabel("Point \(index + 1) demand percent")
            Text("%").foregroundStyle(.secondary)
            let values = limits.map { limit -> String in
                let floor = max(model.draft!.baselineRPM, limit.minimum)
                let value = floor + (limit.maximum - floor) * points.wrappedValue[index].fraction
                return value.isFinite ? value.formatted(.number.precision(.fractionLength(0))) : "?"
            }
            Text(values.joined(separator: " / ")).monospacedDigit().frame(width: 150, alignment: .trailing)
            Button { points.wrappedValue.remove(at: index) } label: { Image(systemName: "minus.circle") }
                .buttonStyle(.borderless).frame(width: 24)
                .disabled(points.wrappedValue.count <= 2 || index == points.wrappedValue.count - 1)
                .help("Remove point \(index + 1)").accessibilityLabel("Remove point \(index + 1)")
        }
    }
}

@main struct CoolerCurvesApp: App {
    var body: some Scene {
        Window("Cooling curves", id: "curves") { EditorView() }
            .defaultSize(width: 760, height: 730)
            .windowResizability(.contentMinSize)
    }
}
