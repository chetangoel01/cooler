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
    func writeFan(_ id: Int, mode: Bool, value: Double) throws {
        guard (0...1).contains(id), value.isFinite else { throw CoolerError("Invalid fan write") }
        let key = "F\(id)\(mode ? "Md" : "Tg")"
        let current = try read(key)
        var input = SMCData()
        input.key = code(key); input.command = 6; input.info.size = current.info.size
        let type = text(current.info.type)
        if mode {
            guard type == "ui8 ", input.info.size == 1, value == 0 || value == 1 else { throw CoolerError("Invalid mode write") }
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
        var actual = try self.value(key)
        for _ in 0..<20 {
            if abs(actual - value) < (mode ? 0.5 : 2) || (mode && value == 0 && actual == 3) { return }
            usleep(50_000)
            actual = try self.value(key)
        }
        throw CoolerError("Write readback failed for \(key): requested \(value), observed \(actual)")
    }
    func automatic() throws {
        var failures: [String] = []
        for id in 0..<2 {
            do { try writeFan(id, mode: true, value: 0) }
            catch { failures.append(String(describing: error)); continue }
            // In automatic mode macOS owns the target RPM. Do not write or
            // compare it to zero: this machine immediately publishes its own target.
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
