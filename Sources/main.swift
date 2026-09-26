import Foundation
import Darwin

var stopped: Int32 = 0
signal(SIGTERM) { _ in stopped = 1 }
signal(SIGINT) { _ in stopped = 1 }
signal(SIGPIPE, SIG_IGN)
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
func emit<T: Encodable>(_ value: T) {
    if let data = try? encoder.encode(value) {
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
}
func log(_ message: String) { fputs("\(ISO8601DateFormatter().string(from: Date())) \(message)\n", stderr) }
func requireHardware() throws {
    guard machineModel() == "MacBookPro18,4" else { throw CoolerError("This build is restricted to MacBookPro18,4") }
}
func requireRoot() throws {
    guard geteuid() == 0 else { throw CoolerError("Administrator privileges are required for fan changes") }
}
func conflict() throws -> Bool {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
    p.arguments = ["-x", "Macs Fan Control|Stats|TG Pro|smcFanControl|macfan"]
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    try p.run(); p.waitUntilExit()
    guard p.terminationStatus <= 1 else { throw CoolerError("Cannot check for another fan controller") }
    return p.terminationStatus == 0
}
func secureConfig(_ path: String) throws {
    var metadata = stat()
    guard lstat(path, &metadata) == 0, metadata.st_uid == 0,
          metadata.st_mode & S_IFMT == S_IFREG, metadata.st_mode & 0o022 == 0 else {
        throw CoolerError("Installed configuration must be a root-owned regular file, not group/world writable")
    }
}
func acquireLock() throws -> Int32 {
    let fd = open("/var/run/com.chetangoel.cooler.lock", O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
    guard fd >= 0, flock(fd, LOCK_EX | LOCK_NB) == 0 else {
        if fd >= 0 { close(fd) }
        throw CoolerError("Another Cooler instance owns fan control; stop the service first")
    }
    return fd
}
func probe() throws {
    let smc = try SMC()
    var values: [String: Double] = [:]
    for key in try smc.keys() where key.hasPrefix("T") || key.hasPrefix("F") {
        if let value = try? smc.value(key) { values[key] = value }
    }
    struct Probe: Encodable { let model: String; let time: String; let values: [String:Double] }
    emit(Probe(model: machineModel(), time: ISO8601DateFormatter().string(from: Date()), values: values))
}
func watchdog(_ parent: pid_t, restore: () throws -> Void) throws {
    guard parent > 1, getppid() == parent else { throw CoolerError("Watchdog requires its controller parent") }
    FileHandle.standardOutput.write(Data("ready\n".utf8))
    var ownsFans = false
    var last = ProcessInfo.processInfo.systemUptime
    var buffer = [UInt8](repeating: 0, count: 256)
    while stopped == 0 {
        var descriptor = pollfd(fd: STDIN_FILENO, events: Int16(POLLIN | POLLHUP), revents: 0)
        let result = poll(&descriptor, 1, 1000)
        if result > 0 {
            let n = read(STDIN_FILENO, &buffer, buffer.count)
            if n <= 0 { break }
            ownsFans = buffer[Int(n)-1] == 1
            last = ProcessInfo.processInfo.systemUptime
        }
        if ProcessInfo.processInfo.systemUptime - last > 10 {
            log("Controller heartbeat timed out; terminating controller")
            kill(parent, SIGKILL)
            break
        }
    }
    if ownsFans {
        // A root daemon restart also restores automatic mode before taking control.
        try restore()
    }
}
func run(_ configPath: String, dry: Bool, samples: Int) throws {
    try requireHardware()
    let config = try Config.load(configPath)
    let smc = try SMC()
    let controller = Controller(config)
    var watchdogProcess: Process?
    var heartbeat: FileHandle?
    var lockFD: Int32 = -1
    if !dry {
        try requireRoot(); try secureConfig(configPath)
        lockFD = try acquireLock()
    }
    let process = Process(), beats = Pipe(), ready = Pipe()
    process.executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
    process.arguments = [dry ? "watch-dry" : "watch", String(getpid())]
    process.standardInput = beats; process.standardOutput = ready
    try process.run()
    // No hardware writes or healthy status before watchdog initialization succeeds.
    let response = ready.fileHandleForReading.availableData
    guard String(data: response, encoding: .utf8) == "ready\n" else { throw CoolerError("Watchdog failed to start") }
    watchdogProcess = process; heartbeat = beats.fileHandleForWriting
    beats.fileHandleForReading.closeFile()
    // Recover a manual setting left by an earlier crash, but respect other tools.
    if !dry { if try !conflict() { try smc.automatic() } }
    defer {
        if !dry && controller.ownsFans {
            do { try smc.automatic(); log("Restored automatic fan control") }
            catch { log("Restore failed: \(error). Watchdog will retry.") }
        }
        heartbeat?.closeFile()
        watchdogProcess?.waitUntilExit()
        if lockFD >= 0 { close(lockFD) }
    }
    var previousTime = Date(), count = 0
    var previousMode = "", previousReason = ""
    while stopped == 0 && (samples == 0 || count < samples) {
        if let watcher = watchdogProcess, !watcher.isRunning { throw CoolerError("Watchdog exited; refusing further control") }
        var frame = readFrame(smc, config)
        let now = Date()
        frame.elapsed = count == 0 ? 2 : now.timeIntervalSince(previousTime)
        previousTime = now
        if !dry {
            do { frame.conflict = try conflict() }
            catch { frame.error = String(describing: error) }
            if ProcessInfo.processInfo.thermalState == .critical { frame.error = "macOS reports critical thermal pressure" }
        }
        var decision = try controller.step(frame, write: { id, rpm in
            try heartbeat?.write(contentsOf: Data([1]))
            if !dry {
                if try smc.value("F\(id)Md") != 1 { try smc.writeFan(id, mode: true, value: 1) }
                try smc.writeFan(id, mode: false, value: rpm)
            }
        }, restore: { if !dry { try smc.automatic() } })
        decision.time = ISO8601DateFormatter().string(from: Date())
        decision.pid = getpid()
        try heartbeat?.write(contentsOf: Data([controller.ownsFans ? 1 : 0]))
        if dry { emit(decision) }
        else {
            let data = try encoder.encode(decision)
            try data.write(to: URL(fileURLWithPath: "/Library/Application Support/Cooler/status.json"), options: .atomic)
            if decision.mode != previousMode || decision.reason != previousReason {
                log(String(decoding: data, as: UTF8.self))
            }
            previousMode = decision.mode; previousReason = decision.reason
        }
        count += 1
        if samples == 0 || count < samples { usleep(2_000_000) }
    }
}
func replay(_ configPath: String, _ framesPath: String) throws {
    let controller = Controller(try Config.load(configPath))
    let frames = try JSONDecoder().decode([Frame].self, from: Data(contentsOf: URL(fileURLWithPath: framesPath)))
    for frame in frames {
        let decision = try controller.step(frame, write: { id, _ in
            if id == frame.failFan { throw CoolerError("Injected write failure") }
        }, restore: {})
        emit(decision)
    }
}

do {
    let args = Array(CommandLine.arguments.dropFirst())
    switch args.first {
    case "probe": try probe()
    case "auto":
        try requireRoot(); try requireHardware()
        var fd: Int32 = -1
        // bootout returns before the old process has necessarily released its lock.
        for _ in 0..<50 {
            if let acquired = try? acquireLock() { fd = acquired; break }
            usleep(100_000)
        }
        guard fd >= 0 else { throw CoolerError("Cooler is still running; stop the service first") }
        defer { close(fd) }
        try SMC().automatic(); print("Automatic fan control restored")
    case "hardware-check":
        try requireRoot(); try requireHardware()
        let fd = try acquireLock(); defer { close(fd) }
        guard try !conflict() else { throw CoolerError("Quit the other fan controller first") }
        let smc = try SMC()
        defer { do { try smc.automatic() } catch { log("Restoration failed: \(error)") } }
        for id in 0..<2 {
            try smc.writeFan(id, mode: true, value: 1)
            try smc.writeFan(id, mode: false, value: try smc.value("F\(id)Mx"))
        }
        usleep(2_000_000)
        var values: [String:Double] = [:]
        for id in 0..<2 {
            for suffix in ["Md", "Tg", "Ac", "Mx"] {
                let key = "F\(id)\(suffix)"; values[key] = try smc.value(key)
            }
        }
        emit(values)
    case "watch":
        guard args.count == 2, let pid = Int32(args[1]) else { throw CoolerError("watch requires a parent PID") }
        try requireRoot(); try requireHardware()
        let smc = try SMC()
        try watchdog(pid) {
            try smc.automatic()
            log("Watchdog restored automatic fan control")
        }
    case "watch-dry":
        guard args.count == 2, let pid = Int32(args[1]) else { throw CoolerError("watch-dry requires a parent PID") }
        try watchdog(pid) { log("Dry-run watchdog restored automatic control") }
    case "check":
        guard args.count == 2 else { throw CoolerError("check requires a configuration path") }
        try requireHardware()
        let config = try Config.load(args[1])
        let result = try Controller(config).step(readFrame(try SMC(), config), write: { _,_ in }, restore: {})
        guard result.mode == "custom" else { throw CoolerError(result.reason) }
        emit(result)
    case "run":
        guard args.count == 2 else { throw CoolerError("run requires a configuration path") }
        try run(args[1], dry: false, samples: 0)
    case "dry-run":
        guard args.count == 3, let samples = Int(args[2]), (1...300).contains(samples) else { throw CoolerError("dry-run CONFIG SAMPLES (1–300)") }
        try run(args[1], dry: true, samples: samples)
    case "replay":
        guard args.count == 3 else { throw CoolerError("replay CONFIG FRAMES") }
        try replay(args[1], args[2])
    default: print("Cooler: probe | dry-run CONFIG SAMPLES | replay CONFIG FRAMES | run CONFIG | auto")
    }
} catch { log(String(describing: error)); exit(1) }
