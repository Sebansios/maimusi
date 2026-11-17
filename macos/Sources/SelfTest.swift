import Foundation

/// `HangulSpacing --self-test`: drives real sessions through the bundled
/// engines with fixed public sentences and checks the results. Exit code 0
/// on success. Never reads or writes user text.
enum SelfTest {
    private struct Case {
        let keys: String
        let expect: String
    }

    private static func type(_ keys: String, then final: Int32) -> (preedit: String, commit: String, ms: Double) {
        let session = hc_session_new()!
        defer { hc_session_free(session) }
        var out = hc_output()
        EngineHub.shared.withBackend { b in
            for k in keys.unicodeScalars {
                hc_session_key(session, UInt32(HC_KEY_CHAR), k.value, b, &out)
            }
        }
        let t0 = DispatchTime.now()
        EngineHub.shared.withBackend { hc_session_key(session, UInt32(HC_KEY_SPACE), 0, $0, &out) }
        let ms = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1e6
        let preedit = String(cString: out.preedit)
        EngineHub.shared.withBackend { hc_session_key(session, UInt32(final), 0, $0, &out) }
        return (preedit, String(cString: out.commit), ms)
    }

    static func run() -> Int32 {
        var failures = 0
        func check(_ label: String, _ ok: Bool, _ detail: String) {
            print("\(ok ? "PASS" : "FAIL")  \(label): \(detail)")
            if !ok { failures += 1 }
        }
        SegmentEditingSelfTest.run(check: check)
        Wordbook.runSelfTest(check: check)
        Updater.runSelfTest(check: check)
        let hub = EngineHub.shared
        check("light model or Kiwi helper bundled", hub.lightAvailable || hub.helper != nil,
              "light=\(hub.lightAvailable) kiwi=\(hub.helper != nil)")

        // Built-in engine through the full session path. Tab은 띄어쓰기를 적용해 확정한다
        // (Enter는 보이는 그대로 확정하므로 띄어쓰기 검사에 쓰지 않는다).
        if hub.lightAvailable {
            Settings.shared.engineOverride = .light
            let light = type("dkqjwlrkqkddpemfdjrktlsek", then: Int32(HC_KEY_TAB))
            // The light model is weaker; require the classic 가방 ambiguity only.
            check("light: 아버지가방에들어가신다", light.commit.hasPrefix("아버지가 방에 ") && light.commit.replacingOccurrences(of: " ", with: "") == "아버지가방에들어가신다",
                  "\(light.commit) (\(String(format: "%.1f", light.ms)) ms)")
        }

        // Kiwi helper, if bundled.
        if let helper = hub.helper {
            Settings.shared.engineOverride = .kiwi
            helper.start()
            let deadline = Date().addingTimeInterval(20)
            while helper.state != .ready && helper.state != .failed && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            check("kiwi helper ready", helper.state == .ready, "\(helper.state)")
            if helper.state == .ready {
                let cases = [
                    Case(keys: "dkqjwlrkqkddpemfdjrktlsek", expect: "아버지가 방에 들어가신다"),
                    Case(keys: "dPQmsrjftkTdj", expect: "예쁜 걸 샀어"),
                    Case(keys: "sodlfdmsqlrkdhfrjf", expect: "내일은 비가 올걸"),
                    Case(keys: "sksmsgkrrydpdlTek.rmflrhtprosmstkTek", expect: "나는 학교에 있다. 그리고 세 개는 샀다"),
                ]
                for c in cases {
                    let r = type(c.keys, then: Int32(HC_KEY_TAB))
                    check("kiwi: \(c.expect)", r.commit == c.expect, "\(r.commit) (\(String(format: "%.1f", r.ms)) ms)")
                }
                func annotated(_ hangul: String, _ hanja: String, _ suffix: String) -> String {
                    switch Settings.shared.string("hanjaPresentation") {
                    case "hangul_hanja": return "\(hangul)(\(hanja))\(suffix)"
                    case "hanja_hangul": return "\(hanja)(\(hangul))\(suffix)"
                    case "hangulhanja": return "\(hangul)\(hanja)\(suffix)"
                    default: return hanja + suffix
                    }
                }
                let items = hub.candidates("학교에").map(\.0)
                check("hanja before emoji for 학교에", items.first == annotated("학교", "學校", "에"), items.prefix(5).joined(separator: " "))
                let verb = hub.candidates("안녕하다").map(\.0)
                check("hanja for 안녕하다", verb.contains(annotated("안녕", "安寧", "하다")), verb.prefix(5).joined(separator: " "))
                for (source, expected) in [("/", "·"), ("[", "【"), ("]", "】"),
                                            ("'", "‘"), ("괄호", "『』"),
                                            ("알파", "α"), ("오메가", "ω"),
                                            ("[책 이름]", "『책 이름』")] {
                    let symbols = hub.candidates(source).map(\.0)
                    check("symbol \(source)", symbols.contains(expected), symbols.prefix(8).joined(separator: " "))
                }
                let punctuation = hc_session_new()!
                var symbolOut = hc_output()
                hub.withBackend { b in
                    hc_session_key(punctuation, UInt32(HC_KEY_CHAR), 47, b, &symbolOut)
                    hc_session_key(punctuation, UInt32(HC_KEY_SPACE), 0, b, &symbolOut)
                    hc_session_key(punctuation, UInt32(HC_KEY_SPACE), 0, b, &symbolOut)
                    hc_session_key(punctuation, UInt32(HC_KEY_ENTER), 0, b, &symbolOut)
                }
                check("slash through native session", String(cString: symbolOut.commit) == "·", String(cString: symbolOut.commit))
                hc_session_free(punctuation)
                let ks = Settings.shared.string("hanjaForms") == "ks"
                let strong = hub.candidates("강하다")
                check("hanja forms (\(ks ? "ks" : "education")) for 강하다",
                      strong.first?.0 == annotated("강", ks ? "强" : "強", "하다") && strong.contains { $0.0 == annotated("강", ks ? "強" : "强", "하다") },
                      strong.prefix(3).map { "\($0.0)[\($0.1)]" }.joined(separator: " "))
            }
            helper.stop()
        } else {
            print("SKIP  kiwi helper not bundled")
        }
        Settings.shared.engineOverride = nil
        // Every word offers alternatives: Space in conversion never just commits.
        Settings.shared.engineOverride = hub.lightAvailable ? .light : .kiwi
        let s = hc_session_new()!
        var out = hc_output()
        EngineHub.shared.withBackend { b in
            for k in "rksek".unicodeScalars { hc_session_key(s, UInt32(HC_KEY_CHAR), k.value, b, &out) }
            hc_session_key(s, UInt32(HC_KEY_SPACE), 0, b, &out)
            hc_session_key(s, UInt32(HC_KEY_SPACE), 0, b, &out)
        }
        let notes = (0..<out.candidate_count).map { hc_session_candidate_note(s, $0).map { String(cString: $0) } ?? "" }
        check("romanization candidates for 간다", out.candidate_count >= 4 && String(cString: out.commit).isEmpty,
              (0..<out.candidate_count).compactMap { hc_session_candidate(s, $0).map { String(cString: $0) } }.joined(separator: " ")
              + " [" + notes.joined(separator: ",") + "]")
        hc_session_free(s)
        hub.helper?.stop()
        Settings.shared.engineOverride = nil

        print(failures == 0 ? "self-test passed" : "self-test FAILED (\(failures))")
        return failures == 0 ? 0 : 1
    }
}
