import Foundation

/// The Kiwi engine service (`Contents/Helpers/HangulEngine.app`), spoken to over
/// stdin/stdout with one JSON object per line. Requests wait at most a short
/// timeout; callers fall back to the built-in engine when it is not ready.
/// The helper's stderr is discarded and nothing typed is written anywhere.
final class EngineHelper {
    enum State { case stopped, starting, ready, failed }

    private let executable: URL
    private let lock = NSCondition()
    private var process: Process?
    private var input: FileHandle?
    private var buffer = Data()
    private var responses: [Int: [String: Any]] = [:]
    /// Requests someone is waiting for; late or unwanted replies are dropped.
    private var waiting = Set<Int>()
    private var nextID = 1
    /// Candidate tables are lazy in the service. Warm public fixed text before
    /// exposing readiness so the first user's conversion gets the usual budget.
    private var warmupID: Int?
    private var failures = 0
    private var retryAfter = Date.distantPast
    private(set) var lastUse = Date()
    private var _state = State.stopped
    /// Sent again after every (re)start.
    var configuration: [String: Any] = [:]

    var state: State {
        lock.lock(); defer { lock.unlock() }
        return _state
    }

    init?(bundle: Bundle) {
        let url = bundle.bundleURL.appendingPathComponent("Contents/Helpers/HangulEngine.app/Contents/MacOS/HangulEngine")
        guard FileManager.default.isExecutableFile(atPath: url.path) else { return nil }
        executable = url
    }

    /// Start the helper in the background if it is not running.
    func start() {
        lock.lock()
        defer { lock.unlock() }
        guard _state == .stopped || _state == .failed, Date() >= retryAfter else { return }
        let p = Process()
        p.executableURL = executable
        p.arguments = []
        p.environment = ["LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"]
        let stdin = Pipe(), stdout = Pipe()
        p.standardInput = stdin
        p.standardOutput = stdout
        p.standardError = FileHandle.nullDevice
        stdout.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            if data.isEmpty {
                h.readabilityHandler = nil
            } else {
                self?.receive(data)
            }
        }
        p.terminationHandler = { [weak self] _ in self?.terminated() }
        do {
            try p.run()
        } catch {
            noteFailure()
            return
        }
        process = p
        input = stdin.fileHandleForWriting
        buffer.removeAll()
        responses.removeAll()
        waiting.removeAll()
        warmupID = nil
        _state = .starting
        lastUse = Date()
    }

    func stop() {
        lock.lock()
        let p = process
        process = nil
        input = nil
        warmupID = nil
        _state = .stopped
        lock.broadcast()
        lock.unlock()
        p?.terminate()
    }

    private func noteFailure() {
        Log.lifecycle.error("engine helper failed (\(self.failures + 1) in a row)")
        failures += 1
        _state = .failed
        // Back off so a broken helper does not respawn on every key.
        retryAfter = Date().addingTimeInterval(min(300, 5 * pow(2, Double(min(failures, 6)))))
    }

    private func terminated() {
        lock.lock()
        if _state != .stopped {
            process = nil
            input = nil
            noteFailure()
        }
        lock.broadcast()
        lock.unlock()
    }

    private func receive(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer.subdata(in: buffer.startIndex..<nl)
            buffer.removeSubrange(buffer.startIndex...nl)
            guard let obj = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
            if obj["op"] as? String == "ready" {
                guard _state == .starting else { continue }
                if obj["ok"] as? Bool == true {
                    sendLocked(configuration.merging(["op": "configure"]) { $1 }, expectReply: false)
                    warmupID = sendLocked(["op": "candidates", "word": "학교"])
                    if warmupID == nil { noteFailure() }
                } else {
                    noteFailure()
                }
            } else if let id = obj["id"] as? Int, id == warmupID {
                warmupID = nil
                if obj["ok"] as? Bool == true {
                    sendLocked(configuration.merging(["op": "configure"]) { $1 }, expectReply: false)
                    Log.lifecycle.notice("engine helper ready")
                    _state = .ready
                    failures = 0
                } else {
                    noteFailure()
                    process?.terminate()
                }
            } else if let id = obj["id"] as? Int, waiting.contains(id) {
                responses[id] = obj
            }
            lock.broadcast()
        }
    }

    @discardableResult
    private func sendLocked(_ request: [String: Any], expectReply: Bool = true) -> Int? {
        guard let input else { return nil }
        let id = nextID
        nextID += 1
        var req = request
        req["id"] = id
        guard var data = try? JSONSerialization.data(withJSONObject: req) else { return nil }
        data.append(0x0A)
        do {
            try input.write(contentsOf: data)
        } catch {
            return nil
        }
        return expectReply ? id : nil
    }

    /// Send a request and wait for its reply. Nil when not ready or too slow.
    func request(_ request: [String: Any], timeout: TimeInterval) -> [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        lastUse = Date()
        guard _state == .ready, let id = sendLocked(request) else { return nil }
        waiting.insert(id)
        defer { waiting.remove(id) }
        let deadline = Date().addingTimeInterval(timeout)
        while responses[id] == nil && _state == .ready {
            if !lock.wait(until: deadline) { break }
        }
        guard let reply = responses.removeValue(forKey: id), reply["ok"] as? Bool == true else { return nil }
        return reply
    }

    /// Engine options sent with `configure` (spacing rules, hanja forms).
    func configure(_ options: [String: Any]) {
        lock.lock()
        defer { lock.unlock() }
        configuration = options
        if _state == .ready {
            sendLocked(options.merging(["op": "configure"]) { $1 }, expectReply: false)
        }
    }
}
