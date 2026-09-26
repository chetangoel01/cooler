import Foundation

struct Point: Codable { let temperature: Double; let fraction: Double }
struct Config: Codable {
    let model: String
    let baselineRPM: Double
    let fallRPMPerSecond: Double
    let cpuKeys: [String]
    let gpuKeys: [String]
    let palmKeys: [String]
    let curve: [Point]
    let palmCurve: [Point]
    static func load(_ path: String) throws -> Config {
        let config = try JSONDecoder().decode(Config.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
        guard config.model == "MacBookPro18,4", (1200...2500).contains(config.baselineRPM),
              (10...100).contains(config.fallRPMPerSecond),
              [config.cpuKeys, config.gpuKeys, config.palmKeys].allSatisfy({ !$0.isEmpty && $0.allSatisfy { $0.utf8.count == 4 && $0.hasPrefix("T") } }) else {
            throw CoolerError("Invalid configuration or unsupported model")
        }
        for curve in [config.curve, config.palmCurve] {
            guard curve.count >= 2, curve.last!.fraction == 1,
                  curve.allSatisfy({ $0.temperature.isFinite && (10...90).contains($0.temperature) && (0...1).contains($0.fraction) }) else { throw CoolerError("Invalid curve") }
            for (a,b) in zip(curve, curve.dropFirst()) {
                guard b.temperature > a.temperature, b.fraction >= a.fraction else { throw CoolerError("Curve must increase monotonically") }
            }
        }
        return config
    }
}
struct Frame: Codable {
    var cpu: Double?
    var gpu: Double?
    var palm: Double?
    var conflict: Bool?
    var elapsed: Double?
    var maxRPM: [Double]?
    var minRPM: [Double]?
    var failFan: Int?
    var error: String?
}
struct Decision: Codable {
    var time: String?
    var mode: String
    var reason: String
    var cpu: Double?
    var gpu: Double?
    var palm: Double?
    var targets: [Double] = []
    var restoredFans: [Int] = []
}

// The real device and replay CLI share the complete decision + write transaction.
final class Controller {
    let config: Config
    private var previous: [Double]?
    private var healthy = 3
    var ownsFans = false
    init(_ config: Config) { self.config = config }
    func fraction(_ temperature: Double, _ curve: [Point]) -> Double {
        if temperature <= curve[0].temperature { return curve[0].fraction }
        for (a,b) in zip(curve, curve.dropFirst()) where temperature <= b.temperature {
            return a.fraction + (b.fraction-a.fraction) * (temperature-a.temperature) / (b.temperature-a.temperature)
        }
        return curve.last!.fraction
    }
    func step(_ frame: Frame, write: (Int, Double) throws -> Void, restore: () throws -> Void) throws -> Decision {
        var result = Decision(mode: "automatic", reason: "", cpu: frame.cpu, gpu: frame.gpu, palm: frame.palm)
        let maxima = frame.maxRPM ?? [5779,6241], minima = frame.minRPM ?? [1200,1200]
        let dt = frame.elapsed ?? 2
        do {
            if let error = frame.error { throw CoolerError(error) }
            guard frame.conflict != true else { throw CoolerError("Another fan controller is running") }
            guard dt > 0, dt <= 10 else { throw CoolerError("Resuming after a gap; collecting fresh samples") }
            guard let cpu = frame.cpu, let gpu = frame.gpu, let palm = frame.palm,
                  [cpu,gpu,palm].allSatisfy({ $0.isFinite && (5...125).contains($0) }) else { throw CoolerError("Missing or invalid temperature") }
            guard maxima.count == 2, minima.count == 2,
                  zip(minima,maxima).allSatisfy({ $0.isFinite && $1.isFinite && $0 >= 1000 && $1 <= 10000 && $1 > max($0,config.baselineRPM) }) else {
                throw CoolerError("Invalid fan limits")
            }
            healthy += 1
            guard healthy >= 3 else { result.reason = "Waiting for three healthy samples"; return result }
            let demand = max(fraction(cpu,config.curve), fraction(gpu,config.curve), fraction(palm,config.palmCurve))
            let targets = zip(minima,maxima).enumerated().map { i, bounds -> Double in
                let floor = max(bounds.0,config.baselineRPM)
                let requested = floor + (bounds.1-floor)*demand
                return max(requested, (previous?[i] ?? requested) - config.fallRPMPerSecond*dt).rounded()
            }
            // Mark ownership before the first write, including partial-write failures.
            ownsFans = true
            for (id,target) in targets.enumerated() { try write(id,target) }
            previous = targets
            result.mode = "custom"; result.reason = "Cooling curve active"; result.targets = targets
            return result
        } catch {
            healthy = 0; previous = nil
            result.reason = String(describing: error)
            if ownsFans {
                try restore()
                ownsFans = false
                result.restoredFans = [0,1]
            }
            return result
        }
    }
}

func readFrame(_ smc: SMC, _ config: Config) -> Frame {
    func hottest(_ keys: [String]) throws -> Double {
        let values = try keys.map { try smc.value($0) }
        guard values.allSatisfy({ (5...125).contains($0) }) else { throw CoolerError("Invalid sensor reading") }
        return values.max()!
    }
    do {
        guard try smc.value("FNum") == 2 else { throw CoolerError("Expected two fans") }
        return Frame(cpu: try hottest(config.cpuKeys), gpu: try hottest(config.gpuKeys), palm: try hottest(config.palmKeys),
                     maxRPM: try (0..<2).map { try smc.value("F\($0)Mx") }, minRPM: try (0..<2).map { try smc.value("F\($0)Mn") })
    } catch { return Frame(error: String(describing: error)) }
}
