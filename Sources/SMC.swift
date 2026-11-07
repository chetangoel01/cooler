// SMC wire layout follows exelban/Stats (MIT); see THIRD_PARTY_NOTICES.md.
import Foundation
import IOKit

struct CoolerError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

private struct SMCData {
    struct Version { var major: UInt8 = 0; var minor: UInt8 = 0; var build: UInt8 = 0; var reserved: UInt8 = 0; var release: UInt16 = 0 }
    struct Limit { var version: UInt16 = 0; var length: UInt16 = 0; var cpu: UInt32 = 0; var gpu: UInt32 = 0; var memory: UInt32 = 0 }
    struct Info { var size: UInt32 = 0; var type: UInt32 = 0; var attributes: UInt8 = 0 }
    var key: UInt32 = 0
    var version = Version()
    var limit = Limit()
    var info = Info()
    var padding: UInt16 = 0
    var result: UInt8 = 0
    var status: UInt8 = 0
    var command: UInt8 = 0
    var index: UInt32 = 0
    var bytes: (UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8,
                UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8,
                UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8,
                UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8, UInt8) =
               (0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)
}

final class SMC {
    private var connection: io_connect_t = 0
    init() throws {
        guard MemoryLayout<SMCData>.stride == 80 else { throw CoolerError("Unexpected SMC wire layout") }
        let service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("AppleSMC"))
        guard service != 0 else { throw CoolerError("AppleSMC unavailable") }
        defer { IOObjectRelease(service) }
        let status = IOServiceOpen(service, mach_task_self_, 0, &connection)
        guard status == KERN_SUCCESS else { throw CoolerError("SMC open failed: \(status)") }
    }
    deinit { IOServiceClose(connection) }
    private func code(_ key: String) -> UInt32 { key.utf8.reduce(0) { ($0 << 8) | UInt32($1) } }
    private func text(_ value: UInt32) -> String {
        String(bytes: [24,16,8,0].map { UInt8((value >> $0) & 255) }, encoding: .ascii) ?? "????"
    }
    private func call(_ input: SMCData) throws -> SMCData {
        var input = input, output = SMCData()
        var size = MemoryLayout<SMCData>.stride
        let status = IOConnectCallStructMethod(connection, 2, &input, size, &output, &size)
        guard status == KERN_SUCCESS, output.result == 0, size == 80 else {
            throw CoolerError("SMC \(text(input.key)) operation \(input.command): IOKit \(status), SMC \(output.result)")
        }
        return output
    }
    private func read(_ key: String) throws -> SMCData {
        guard key.utf8.count == 4 else { throw CoolerError("Invalid SMC key") }
        var input = SMCData(); input.key = code(key); input.command = 9
        let metadata = try call(input)
        guard (1...32).contains(metadata.info.size) else { throw CoolerError("Invalid size for \(key)") }
        input.info = metadata.info; input.command = 5
        var output = try call(input); output.info = metadata.info
        return output
    }
    func value(_ key: String) throws -> Double {
        var output = try read(key)
        let bytes = withUnsafeBytes(of: &output.bytes) { Array($0) }
        let value: Double
        switch (text(output.info.type), output.info.size) {
        case ("flt ", 4):
            let bits = UInt32(bytes[0]) | (UInt32(bytes[1]) << 8) | (UInt32(bytes[2]) << 16) | (UInt32(bytes[3]) << 24)
            value = Double(Float(bitPattern: bits))
        case ("ui8 ", 1): value = Double(bytes[0])
        case ("ui16", 2): value = Double(UInt16(bytes[0]) << 8 | UInt16(bytes[1]))
        case ("ui32", 4): value = Double(bytes.prefix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) })
        case ("sp78", 2): value = Double(Int16(bitPattern: UInt16(bytes[0]) << 8 | UInt16(bytes[1]))) / 256
        case ("fpe2", 2): value = Double(UInt16(bytes[0]) << 8 | UInt16(bytes[1])) / 4
        default: throw CoolerError("Unsupported SMC type \(text(output.info.type)) for \(key)")
        }
        guard value.isFinite else { throw CoolerError("Non-finite value for \(key)") }
        return value
    }
    func keys() throws -> [String] {
        let count = Int(try value("#KEY"))
        guard (1...10000).contains(count) else { throw CoolerError("Invalid key count") }
        return try (0..<count).map { index in
            var input = SMCData(); input.command = 8; input.index = UInt32(index)
            return text(try call(input).key)
        }
    }
    // Every readable temperature and fan key, as `cooler probe` reports them.
    func readings() throws -> [String: Double] {
        var values: [String: Double] = [:]
        for key in try keys() where key.hasPrefix("T") || key.hasPrefix("F") {
            if let value = try? self.value(key) { values[key] = value }
        }
        return values
    }
    func fans() throws -> (count: Int, modeKey: String) { try fanLayout { try? value($0) } }
    func writeFan(_ id: Int, mode: Bool, value: Double) throws {
        let fans = try self.fans()
        guard (0..<fans.count).contains(id), value.isFinite else { throw CoolerError("Invalid fan write") }
        try write("F\(id)\(mode ? fans.modeKey : "Tg")", flag: mode, value: value)
    }
    // Writes a one-byte flag (a fan mode or Ftst) or a float RPM target.
    private func write(_ key: String, flag: Bool, value: Double) throws {
        let current = try read(key)
        var input = SMCData()
        input.key = code(key); input.command = 6; input.info.size = current.info.size
        let type = text(current.info.type)
        if flag {
            guard type == "ui8 " || type == "flag", input.info.size == 1, value == 0 || value == 1 else { throw CoolerError("Invalid flag write to \(key)") }
            input.bytes.0 = UInt8(value)
        } else {
            guard type == "flt ", input.info.size == 4, (0...10000).contains(value) else { throw CoolerError("Invalid RPM write") }
            let bits = Float(value).bitPattern
            input.bytes.0 = UInt8(bits & 255); input.bytes.1 = UInt8((bits >> 8) & 255)
            input.bytes.2 = UInt8((bits >> 16) & 255); input.bytes.3 = UInt8((bits >> 24) & 255)
        }
        _ = try call(input)
        // Some SMC keys expose their old value briefly after a successful write.
        // Poll the readback, never retry an unverified mutation indefinitely.
        func observed() throws -> Double { flag ? Double(try read(key).bytes.0) : try self.value(key) }
        var actual = try observed()
        for _ in 0..<20 {
            if abs(actual - value) < (flag ? 0.5 : 2) || (flag && value == 0 && actual == 3) { return }
            usleep(50_000)
            actual = try observed()
        }
        throw CoolerError("Write readback failed for \(key): requested \(value), observed \(actual)")
    }
    private func retrying(for seconds: TimeInterval, _ waiting: () throws -> Void, _ attempt: () throws -> Void) throws {
        let deadline = ProcessInfo.processInfo.systemUptime + seconds
        while true {
            do { return try attempt() } catch { if ProcessInfo.processInfo.systemUptime >= deadline { throw error } }
            try waiting(); usleep(100_000)
        }
    }
    // The thermal-manager unlock flag, nil on Macs without it (the M1 Max, M5 Pro and M6 mini).
    func unlockFlag() -> UInt8? {
        guard let output = try? read("Ftst"), output.info.size == 1 else { return nil }
        return output.bytes.0
    }
    // Puts one fan in manual mode. The direct write works on the M1 Max, M5 Pro and M6
    // mini. On M3 and M4 Macs macOS's thermal manager refuses mode and target writes
    // while it holds the fans; there, as Stats does, set Ftst so it lets go (3–6 s in
    // the research Stats follows) and retry. `waiting` runs between attempts so the
    // watchdog keeps hearing from the controller.
    func manual(_ id: Int, waiting: () throws -> Void = {}) throws {
        if try value("F\(id)\(fans().modeKey)") == 1 { return }
        do { try writeFan(id, mode: true, value: 1) } catch {
            guard let unlock = unlockFlag() else { throw error }
            if unlock != 1 { try retrying(for: 5, waiting) { try write("Ftst", flag: true, value: 1) } }
            try retrying(for: 30, waiting) { try writeFan(id, mode: true, value: 1) }
        }
    }
    // Hands every fan back to macOS. Fans already in automatic (0) or system (3) mode
    // are left alone, since an M3 or M4 Mac refuses mode writes while macOS holds the
    // fans. Ftst is cleared last, whoever set it and even if the fans cannot be read,
    // so macOS's thermal manager takes the fans back.
    func automatic() throws {
        var failures: [String] = []
        do {
            let fans = try self.fans()
            for id in 0..<fans.count {
                do {
                    let mode = try value("F\(id)\(fans.modeKey)")
                    if mode != 0 && mode != 3 { try writeFan(id, mode: true, value: 0) }
                } catch { failures.append(String(describing: error)) }
                // In automatic mode macOS owns the target RPM. Do not write or
                // compare it to zero: this machine immediately publishes its own target.
            }
        } catch { failures.append(String(describing: error)) }
        if let unlock = unlockFlag(), unlock != 0 {
            do { try retrying(for: 1, {}) { try write("Ftst", flag: true, value: 0) } }
            catch { failures.append(String(describing: error)) }
        }
        if !failures.isEmpty { throw CoolerError(failures.joined(separator: "; ")) }
    }
}

func machineModel() -> String {
    var length = 0
    sysctlbyname("hw.model", nil, &length, nil, 0)
    var bytes = [CChar](repeating: 0, count: length)
    sysctlbyname("hw.model", &bytes, &length, nil, 0)
    return String(cString: bytes)
}
