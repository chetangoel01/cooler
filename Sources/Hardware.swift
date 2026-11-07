// Which SMC keys hold the CPU, GPU and palm-rest temperatures, and how the fans
// are addressed, for each Apple silicon generation. The listed M1–M4 keys and M5
// CPU keys follow Stats (exelban/stats, MIT), retrieved 2026-11-07; see
// THIRD_PARTY_NOTICES.md. Lists are unions across a generation's variants, so
// keys a Mac lacks are skipped. The prefix rules come from load tests on an M5 Pro
// (artifacts/m5-sensor-discovery.json) and an M6 Mac mini (m6-sensor-discovery.json).
import Foundation

struct Hardware: Codable {
    let cpu: [String]
    let gpu: [String]
    let palm: [String]   // empty on desktops
    let fans: Int
    let modeKey: String  // manual-mode key suffix: "md" from M5 on, "Md" before
}

private enum Sensors {
    case listed([String])
    case prefixed(String)  // every key with this prefix
    func select(_ values: [String: Double]) -> [String] {
        switch self {
        case .listed(let keys): return keys.filter { values[$0] != nil }
        case .prefixed(let prefix): return values.keys.filter { $0.hasPrefix(prefix) }.sorted()
        }
    }
}
private let chips: [Int: (cpu: Sensors, gpu: Sensors)] = [
    1: (.listed(["Tp09", "Tp0T", "Tp01", "Tp05", "Tp0D", "Tp0H", "Tp0L", "Tp0P", "Tp0X", "Tp0b"]),
        .listed(["Tg05", "Tg0D", "Tg0L", "Tg0T"])),
    2: (.listed(["Tp1h", "Tp1t", "Tp1p", "Tp1l", "Tp01", "Tp05", "Tp09", "Tp0D", "Tp0X", "Tp0b", "Tp0f", "Tp0j"]),
        .listed(["Tg0f", "Tg0j"])),
    3: (.listed(["Te05", "Te0L", "Te0P", "Te0S", "Tf04", "Tf09", "Tf0A", "Tf0B", "Tf0D", "Tf0E",
                 "Tf44", "Tf49", "Tf4A", "Tf4B", "Tf4D", "Tf4E"]),
        .listed(["Tf14", "Tf18", "Tf19", "Tf1A", "Tf24", "Tf28", "Tf29", "Tf2A"])),
    4: (.listed(["Te05", "Te0S", "Te09", "Te0H", "Tp01", "Tp05", "Tp09", "Tp0D", "Tp0V", "Tp0Y", "Tp0b", "Tp0e"]),
        .listed(["Tg0G", "Tg0H", "Tg1U", "Tg1k", "Tg0K", "Tg0L", "Tg0d", "Tg0e", "Tg0j", "Tg0k"])),
    5: (.listed(["Tp00", "Tp04", "Tp08", "Tp0C", "Tp0G", "Tp0K", "Tp0O", "Tp0R", "Tp0U",
                 "Tp0X", "Tp0a", "Tp0d", "Tp0g", "Tp0j", "Tp0m", "Tp0p", "Tp0u", "Tp0y"]),
        .prefixed("Tg")),
    6: (.prefixed("Tp0"), .prefixed("Tg")),
]
private let palmKeys = ["Ts0P", "Ts1P"]

func cpuBrand() -> String {
    var length = 0
    sysctlbyname("machdep.cpu.brand_string", nil, &length, nil, 0)
    var bytes = [CChar](repeating: 0, count: length)
    sysctlbyname("machdep.cpu.brand_string", &bytes, &length, nil, 0)
    return String(cString: bytes)
}

// "Apple M1 Max" → 1, "Apple M6" → 6. Anything else, including an Intel CPU or a
// newer generation, has no known sensor keys and is refused.
func chipGeneration(_ brand: String) throws -> Int {
    let prefix = "Apple M"
    let digits = brand.hasPrefix(prefix) ? brand.dropFirst(prefix.count).prefix(while: \.isNumber) : ""
    guard let generation = Int(digits), chips[generation] != nil else {
        throw CoolerError("Cooler has no sensor map for \(brand.isEmpty ? "this chip" : brand)")
    }
    return generation
}

// `read` returns nil for keys this Mac does not have.
func fanLayout(_ read: (String) -> Double?) throws -> (count: Int, modeKey: String) {
    guard let count = read("FNum"), (1...8).contains(count), count.rounded() == count else {
        throw CoolerError("This Mac has no fans Cooler can control")
    }
    return (Int(count), read("F0md") != nil ? "md" : "Md")
}

// `values` holds every readable T and F key, as `cooler probe` reports them.
func hardware(brand: String, values: [String: Double]) throws -> Hardware {
    let chip = chips[try chipGeneration(brand)]!
    let fans = try fanLayout { values[$0] }
    let missing = (0..<fans.count).flatMap { id in [fans.modeKey, "Tg", "Mn", "Mx", "Ac"].map { "F\(id)\($0)" } }
        .filter { values[$0] == nil }
    guard missing.isEmpty else { throw CoolerError("This Mac lacks the fan keys Cooler uses: \(missing.joined(separator: ", "))") }
    let cpu = chip.cpu.select(values), gpu = chip.gpu.select(values)
    guard !cpu.isEmpty, !gpu.isEmpty else { throw CoolerError("None of the known \(brand) sensors are present") }
    return Hardware(cpu: cpu, gpu: gpu, palm: Sensors.listed(palmKeys).select(values), fans: fans.count, modeKey: fans.modeKey)
}
