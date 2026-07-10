// TickyWidget: the macOS frontend for ticky — status item + native setup window.
// Status item: glyph gains a count while subagents run; menu shows who called
// what and why. Setup window: backends (subscription login / API keys), agent
// roster editor (name, backend, model, access, workdir, priority, specialty),
// routing preferences, and one primary button that writes config and installs
// into bosses. Opens on first run (no config), via `ticky setup` (flag file),
// or from the menu.
// This file is deliberately the only macOS-specific part of ticky; ports for
// other platforms live beside it in widget/<platform>/.
// Built by `ticky widget build` into ~/.ticky/bin/ticky-widget. No app bundle.

import AppKit

let home = NSString(string: "~").expandingTildeInPath
let tickyHome = (ProcessInfo.processInfo.environment["TICKY_HOME"] as NSString?)?.expandingTildeInPath
    ?? home + "/.ticky"
let statePath = tickyHome + "/state.json"
let logPath = tickyHome + "/calls.jsonl"
let configPath = tickyHome + "/config.json"
let envPath = tickyHome + "/env"
let setupFlagPath = tickyHome + "/open-setup"

func tickyCli() -> String {
    for p in [home + "/.local/bin/ticky", home + "/ticky/ticky"] where FileManager.default.isExecutableFile(atPath: p) {
        return p
    }
    return "ticky"
}

// ---------------------------------------------------------------- palette

// Ticky's own scheme instead of wall-to-wall system gray: a warm brass brand
// color plus one jewel tone per agent, each with light and dark variants.
enum Palette {
    static func dynamic(light: NSColor, dark: NSColor) -> NSColor {
        NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        }
    }

    static func hex(_ v: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((v >> 16) & 0xFF) / 255,
                green: CGFloat((v >> 8) & 0xFF) / 255,
                blue: CGFloat(v & 0xFF) / 255, alpha: 1)
    }

    static let brand = dynamic(light: hex(0xA9701D), dark: hex(0xE2A85C))      // brass
    static let onBrand = dynamic(light: .white, dark: hex(0x2A1D0A))
    static let rook = dynamic(light: hex(0x44579B), dark: hex(0x93A5E8))       // indigo
    static let wren = dynamic(light: hex(0xB05733), dark: hex(0xE8916B))       // terracotta
    static let finch = dynamic(light: hex(0x5F7F2E), dark: hex(0xA3C063))      // olive
    static let spare: [NSColor] = [
        dynamic(light: hex(0x7A4E8F), dark: hex(0xC49BDD)),                    // plum
        dynamic(light: hex(0x2E7D7B), dark: hex(0x7CC5C2)),                    // teal
        dynamic(light: hex(0x9C4553), dark: hex(0xE096A2)),                    // rosewood
    ]

    static func agent(_ name: String, index: Int) -> NSColor {
        switch name {
        case "rook": return rook
        case "wren": return wren
        case "finch": return finch
        default: return spare[abs(index) % spare.count]
        }
    }
}

// ------------------------------------------------------------ config model

struct AgentCfg: Codable {
    var name: String
    var display: String
    var backend: String
    var model: String?
    var specialty: String
    var routing_note: String
    var priority: Int
    var access: String
    var workdir: String
    var network: Bool
    var timeout: Int
    var enabled: Bool
    var extra_args: [String]

    static func fresh(_ display: String, backend: String) -> AgentCfg {
        AgentCfg(name: display.lowercased(), display: display, backend: backend, model: nil,
                 specialty: "", routing_note: "", priority: 2, access: "read-only",
                 workdir: "~", network: false, timeout: 900, enabled: true, extra_args: [])
    }
}

struct TickyCfg: Codable {
    var version: Int
    var preferences: String
    var agents: [AgentCfg]

    // keep in sync with DEFAULT_AGENTS / DEFAULT_PREFS in the ticky CLI
    static let rookSpecialty = "Deep reasoning: audits, math, second opinions on plans, tricky debugging analysis."
    static let wrenSpecialty = "Research, reading long documents, summarization, and drafting prose or docs."
    static let finchSpecialty = "Hands-on coding: multi-file edits, running builds and tests, agentic tool work inside a repo."
    static let defaultShortRoles: [String: String] = [
        rookSpecialty: "Deep reasoning and review",
        wrenSpecialty: "Research and writing",
        finchSpecialty: "Hands-on coding",
    ]

    static func defaults() -> TickyCfg {
        var rook = AgentCfg.fresh("Rook", backend: "codex")
        rook.specialty = rookSpecialty
        rook.routing_note = "Call Rook first for anything analytical or verification-shaped."
        rook.priority = 1
        var wren = AgentCfg.fresh("Wren", backend: "codex")
        wren.specialty = wrenSpecialty
        wren.routing_note = "Call Wren for research and writing tasks."
        wren.priority = 1
        var finch = AgentCfg.fresh("Finch", backend: "claude")
        finch.specialty = finchSpecialty
        finch.routing_note = "Call Finch when files actually need to change."
        finch.access = "workspace-write"
        return TickyCfg(
            version: 1,
            preferences: "ChatGPT credits are ample and Claude tokens are scarcer: when a task fits "
                + "more than one agent, prefer the codex-backed ones (Rook, Wren) over the "
                + "claude-backed one (Finch). Lower priority number means call first. Always "
                + "pass a specific one-line reason; it is logged and shown in the ticky widget.",
            agents: [rook, wren, finch])
    }

    static func load() -> TickyCfg? {
        guard let data = FileManager.default.contents(atPath: configPath) else { return nil }
        return try? JSONDecoder().decode(TickyCfg.self, from: data)
    }

    func save() throws {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted]
        let data = try enc.encode(self)
        try FileManager.default.createDirectory(atPath: tickyHome, withIntermediateDirectories: true)
        try data.write(to: URL(fileURLWithPath: configPath), options: .atomic)
    }
}

// -------------------------------------------------------------- auth + env

func loadEnvFile() -> [String: String] {
    guard let text = try? String(contentsOfFile: envPath, encoding: .utf8) else { return [:] }
    var out: [String: String] = [:]
    for line in text.split(separator: "\n") {
        let t = line.trimmingCharacters(in: .whitespaces)
        if t.isEmpty || t.hasPrefix("#") { continue }
        guard let eq = t.firstIndex(of: "=") else { continue }
        out[String(t[..<eq])] = String(t[t.index(after: eq)...])
    }
    return out
}

func saveEnvKey(_ key: String, _ value: String) throws {
    var env = loadEnvFile()
    env[key] = value
    let text = env.map { "\($0.key)=\($0.value)" }.joined(separator: "\n") + "\n"
    try FileManager.default.createDirectory(atPath: tickyHome, withIntermediateDirectories: true)
    try text.write(toFile: envPath, atomically: true, encoding: .utf8)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: envPath)
}

func backendAuthStatus(_ backend: String) -> (ok: Bool, detail: String) {
    let fm = FileManager.default
    let env = loadEnvFile()
    if backend == "codex" {
        if !cliExists("codex") { return (false, "codex CLI not installed") }
        if env["OPENAI_API_KEY"] != nil { return (true, "API key stored") }
        if fm.fileExists(atPath: home + "/.codex/auth.json") { return (true, "ChatGPT subscription login") }
        return (false, "installed, not signed in")
    } else {
        if !cliExists("claude") { return (false, "claude CLI not installed") }
        if env["ANTHROPIC_API_KEY"] != nil { return (true, "API key stored") }
        if fm.fileExists(atPath: home + "/.claude/.credentials.json") { return (true, "subscription login") }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        p.arguments = ["find-generic-password", "-s", "Claude Code-credentials"]
        p.standardOutput = Pipe(); p.standardError = Pipe()
        try? p.run(); p.waitUntilExit()
        if p.terminationStatus == 0 { return (true, "subscription login (Keychain)") }
        return (false, "installed, not signed in")
    }
}

func cliExists(_ name: String) -> Bool {
    let candidates = [home + "/.local/bin/" + name, "/opt/homebrew/bin/" + name,
                      "/usr/local/bin/" + name,
                      home + "/.nvm/versions/node", "/usr/bin/" + name]
    for c in candidates {
        if c.contains("/.nvm/") {
            // any nvm node version's bin dir
            if let versions = try? FileManager.default.contentsOfDirectory(atPath: c) {
                for v in versions where FileManager.default.isExecutableFile(atPath: "\(c)/\(v)/bin/\(name)") {
                    return true
                }
            }
        } else if FileManager.default.isExecutableFile(atPath: c) {
            return true
        }
    }
    return false
}

func openTerminal(running command: String) {
    let script = "tell application \"Terminal\"\nactivate\ndo script \"\(command)\"\nend tell"
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    p.arguments = ["-e", script]
    try? p.run()
}

// ------------------------------------------------------------- log reading

struct RunningCall { let agent: String; let reason: String; let started: Date? }
struct LogEntry {
    let ts: Date?; let agent: String; let boss: String
    let reason: String; let status: String; let duration: Double
}

let isoParser: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f
}()

func relative(_ date: Date?) -> String {
    guard let d = date else { return "?" }
    let s = Int(-d.timeIntervalSinceNow)
    if s < 60 { return "\(max(s, 0))s ago" }
    if s < 3600 { return "\(s / 60)m ago" }
    if s < 86400 { return "\(s / 3600)h ago" }
    return "\(s / 86400)d ago"
}

func elapsed(_ date: Date?) -> String {
    guard let d = date else { return "" }
    let s = Int(-d.timeIntervalSinceNow)
    return String(format: "%d:%02d", s / 60, s % 60)
}

func truncate(_ s: String, _ n: Int) -> String {
    s.count <= n ? s : String(s.prefix(n - 1)) + "…"
}

func readState() -> [RunningCall] {
    guard let data = FileManager.default.contents(atPath: statePath),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let running = obj["running"] as? [[String: Any]] else { return [] }
    return running.map {
        RunningCall(agent: $0["agent"] as? String ?? "?",
                    reason: $0["reason"] as? String ?? "",
                    started: ($0["started"] as? String).flatMap { isoParser.date(from: $0) })
    }
}

func readLogTail(_ n: Int) -> [LogEntry] {
    guard let fh = FileHandle(forReadingAtPath: logPath) else { return [] }
    defer { try? fh.close() }
    let size = (try? fh.seekToEnd()) ?? 0
    try? fh.seek(toOffset: size > 65536 ? size - 65536 : 0)
    guard let data = try? fh.readToEnd(), let text = String(data: data, encoding: .utf8) else { return [] }
    var out: [LogEntry] = []
    for line in text.split(separator: "\n").suffix(n) {
        guard let d = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { continue }
        out.append(LogEntry(
            ts: (obj["ts"] as? String).flatMap { isoParser.date(from: $0) },
            agent: obj["agent"] as? String ?? "?",
            boss: obj["boss"] as? String ?? "?",
            reason: obj["reason"] as? String ?? "",
            status: obj["status"] as? String ?? "?",
            duration: obj["duration_s"] as? Double ?? Double(obj["duration_s"] as? Int ?? 0)))
    }
    return out.reversed()
}

func callsToday() -> Int {
    guard let text = try? String(contentsOfFile: logPath, encoding: .utf8) else { return 0 }
    var count = 0
    for line in text.split(separator: "\n") {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let raw = obj["ts"] as? String,
              let date = isoParser.date(from: raw) else { continue }
        if Calendar.current.isDateInToday(date) { count += 1 }
    }
    return count
}

// -------------------------------------------------------------- row view

// A row that selects on any click that no real control claims first. Subview
// hit-testing is resolved here (in the superview coordinate space AppKit hands
// us) so the include checkbox and the inline editor keep working while the
// rest of the row is one big click target. This replaces the old
// NSClickGestureRecognizer approach, which fought the controls for events and
// tested coordinates in the wrong space.
final class AgentRowView: NSBox {
    var onSelect: (() -> Void)?

    override func hitTest(_ point: NSPoint) -> NSView? {
        guard let deepest = super.hitTest(point) else { return nil }
        var view: NSView? = deepest
        while let current = view, current !== self {
            if current is NSButton { return deepest }
            if let field = current as? NSTextField, field.isEditable { return deepest }
            view = current.superview
        }
        return self
    }

    override func mouseDown(with event: NSEvent) {
        onSelect?()
    }

    // Selecting a row should work on the first click even when the window is
    // in the background, like any list row.
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // Rows are interactive; expose them as buttons so VoiceOver and other
    // assistive tools can select agents too.
    override func isAccessibilityElement() -> Bool { true }
    override func accessibilityRole() -> NSAccessibility.Role? { .button }
    override func accessibilityPerformPress() -> Bool {
        onSelect?()
        return true
    }
}

// ------------------------------------------------------------ setup window

final class SetupWindowController: NSWindowController, NSWindowDelegate, NSTableViewDataSource,
                                   NSTableViewDelegate, NSTextFieldDelegate {
    var cfg: TickyCfg
    var selected: Int
    var showingAdvanced = false
    var suppressSelectionCallback = false
    var advancedConfigured = false

    let table = NSTableView()
    let codexStatus = NSTextField(labelWithString: "")
    let claudeStatus = NSTextField(labelWithString: "")
    let codexKeyField = NSSecureTextField()
    let claudeKeyField = NSSecureTextField()
    let prefsView = NSTextView()
    let statusLabel = NSTextField(labelWithString: "")
    let installButton = NSButton(title: "Install Team", target: nil, action: nil)
    let applyButton = NSButton(title: "Save and Install", target: nil, action: nil)

    // Compact editor used by the startup screen.
    let overviewRoleField = NSTextField()
    let overviewAccessPopup = NSPopUpButton()
    var overviewOriginalRole = ""

    // Full agent editor used by Advanced settings.
    let nameField = NSTextField()
    let toolLabel = NSTextField(labelWithString: "")
    let backendPopup = NSPopUpButton()
    let modelCombo = NSComboBox()
    let accessPopup = NSPopUpButton()
    let priorityPopup = NSPopUpButton()
    let workdirField = NSTextField()
    let timeoutField = NSTextField()
    let specialtyField = NSTextField()
    let noteField = NSTextField()
    let enabledCheck = NSButton(checkboxWithTitle: "Enabled", target: nil, action: nil)
    let networkCheck = NSButton(checkboxWithTitle: "Allow Network Access", target: nil, action: nil)

    init() {
        cfg = TickyCfg.load() ?? TickyCfg.defaults()
        selected = -1
        let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 920, height: 688),
                           styleMask: [.titled, .closable],
                           backing: .buffered, defer: false)
        win.title = "Ticky Setup"
        win.titlebarSeparatorStyle = .none
        win.isOpaque = false
        win.backgroundColor = .windowBackgroundColor
        win.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
        super.init(window: win)
        win.delegate = self
        configureOverviewControls()
        refreshAuth()
        buildOverviewUI()
        win.center()
    }

    required init?(coder: NSCoder) { fatalError() }

    func configureOverviewControls() {
        overviewAccessPopup.addItems(withTitles: ["read-only", "workspace-write", "full"])
        overviewAccessPopup.target = self
        overviewAccessPopup.action = #selector(overviewEditorChanged)
        overviewRoleField.target = self
        overviewRoleField.action = #selector(overviewEditorChanged)
        overviewRoleField.placeholderString = "What should this agent handle?"
        // Constrain the shared editor controls exactly once; the old per-build
        // constraints piled up a duplicate on every selection change.
        overviewRoleField.widthAnchor.constraint(equalToConstant: 276).isActive = true
        overviewAccessPopup.widthAnchor.constraint(equalToConstant: 276).isActive = true
        installButton.target = self
        installButton.action = #selector(installTeam)
        installButton.keyEquivalent = "\r"
        installButton.controlSize = .large
        installButton.bezelStyle = .rounded
        installButton.bezelColor = Palette.brand
        installButton.attributedTitle = brandButtonTitle("Install Team")
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.stringValue = ""
    }

    func brandButtonTitle(_ title: String) -> NSAttributedString {
        NSAttributedString(string: title, attributes: [
            .foregroundColor: Palette.onBrand,
            .font: NSFont.systemFont(ofSize: 13, weight: .medium),
        ])
    }

    func clearContent() {
        guard let content = window?.contentView else { return }
        window?.makeFirstResponder(nil)
        for view in content.subviews { view.removeFromSuperview() }
    }

    func label(_ s: String, size: CGFloat = 12, color: NSColor = .secondaryLabelColor,
               weight: NSFont.Weight = .regular) -> NSTextField {
        let l = NSTextField(labelWithString: s)
        l.font = .systemFont(ofSize: size, weight: weight)
        l.textColor = color
        return l
    }

    func wrappingLabel(_ s: String, size: CGFloat = 13, color: NSColor = .secondaryLabelColor,
                       maxLines: Int = 2) -> NSTextField {
        let l = label(s, size: size, color: color)
        l.maximumNumberOfLines = maxLines
        l.lineBreakMode = .byWordWrapping
        l.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return l
    }

    func symbol(_ name: String, description: String, size: CGFloat = 18,
                color: NSColor = .secondaryLabelColor) -> NSImageView {
        let config = NSImage.SymbolConfiguration(pointSize: size, weight: .regular)
        let image = NSImage(systemSymbolName: name, accessibilityDescription: description)?
            .withSymbolConfiguration(config)
        let view = NSImageView(image: image ?? NSImage())
        view.contentTintColor = color
        view.imageScaling = .scaleProportionallyDown
        view.setAccessibilityLabel(description)
        return view
    }

    func iconTile(_ name: String, description: String, symbolSize: CGFloat = 18,
                  tileSize: CGFloat = 42, color: NSColor = .secondaryLabelColor) -> NSBox {
        let icon = symbol(name, description: description, size: symbolSize, color: color)
        let content = NSView()
        icon.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(icon)
        NSLayoutConstraint.activate([
            icon.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            icon.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            icon.widthAnchor.constraint(lessThanOrEqualToConstant: tileSize - 12),
            icon.heightAnchor.constraint(lessThanOrEqualToConstant: tileSize - 12),
        ])
        let tile = NSBox()
        tile.boxType = .custom
        tile.borderWidth = 0
        tile.cornerRadius = 8
        tile.fillColor = color.withAlphaComponent(0.14)
        tile.contentView = content
        tile.widthAnchor.constraint(equalToConstant: tileSize).isActive = true
        tile.heightAnchor.constraint(equalToConstant: tileSize).isActive = true
        return tile
    }

    func textButton(_ title: String, action: Selector, tint: NSColor = .secondaryLabelColor) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.isBordered = false
        button.font = .systemFont(ofSize: 13)
        button.contentTintColor = tint
        return button
    }

    func separator() -> NSBox {
        let line = NSBox()
        line.boxType = .separator
        return line
    }

    func formRow(_ title: String, _ control: NSView, labelWidth: CGFloat = 82) -> NSStackView {
        let l = label(title)
        l.widthAnchor.constraint(equalToConstant: labelWidth).isActive = true
        let row = NSStackView(views: [l, control])
        row.spacing = 8
        row.alignment = .centerY
        return row
    }

    // ------------------------------------------------------- startup screen

    func buildOverviewUI() {
        clearContent()
        showingAdvanced = false
        window?.title = "Ticky Setup"
        if cfg.agents.isEmpty {
            selected = -1
        } else if selected < -1 || selected >= cfg.agents.count {
            selected = -1
        }

        let title = label("Your Team", size: 28, color: .labelColor, weight: .semibold)
        let subtitle = label("Choose who Ticky can call. You can change this anytime.", size: 14)
        let header = NSStackView(views: [title, subtitle])
        header.orientation = .vertical
        header.alignment = .leading
        header.spacing = 6

        let footerLine = separator()
        let advanced = textButton("Advanced…", action: #selector(showAdvancedSettings))
        advanced.image = NSImage(systemSymbolName: "gearshape", accessibilityDescription: "Advanced settings")
        advanced.imagePosition = .imageLeading
        advanced.bezelStyle = .inline
        statusLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let footer = NSStackView(views: [advanced, statusLabel, NSView(), installButton])
        footer.spacing = 12
        footer.alignment = .centerY

        let team = teamPane()
        let mainRoot = NSStackView(views: [header, team, NSView(), footerLine, footer])
        mainRoot.orientation = .vertical
        mainRoot.alignment = .leading
        mainRoot.spacing = 18

        let sidebar = NSVisualEffectView()
        sidebar.material = .sidebar
        sidebar.blendingMode = .behindWindow
        sidebar.state = .followsWindowActiveState
        let sidebarContent = connectionsPane()
        sidebarContent.translatesAutoresizingMaskIntoConstraints = false
        sidebar.addSubview(sidebarContent)
        NSLayoutConstraint.activate([
            sidebarContent.topAnchor.constraint(equalTo: sidebar.topAnchor, constant: 24),
            sidebarContent.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 22),
            sidebarContent.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -20),
            sidebarContent.bottomAnchor.constraint(equalTo: sidebar.bottomAnchor, constant: -22),
        ])

        let main = NSVisualEffectView()
        main.material = .contentBackground
        main.blendingMode = .withinWindow
        main.state = .followsWindowActiveState
        mainRoot.translatesAutoresizingMaskIntoConstraints = false
        main.addSubview(mainRoot)
        NSLayoutConstraint.activate([
            mainRoot.topAnchor.constraint(equalTo: main.topAnchor, constant: 30),
            mainRoot.leadingAnchor.constraint(equalTo: main.leadingAnchor, constant: 32),
            mainRoot.trailingAnchor.constraint(equalTo: main.trailingAnchor, constant: -32),
            mainRoot.bottomAnchor.constraint(equalTo: main.bottomAnchor, constant: -22),
        ])
        for view in [header, team, footerLine, footer] {
            view.widthAnchor.constraint(equalTo: mainRoot.widthAnchor).isActive = true
        }

        let split = NSView()
        sidebar.translatesAutoresizingMaskIntoConstraints = false
        main.translatesAutoresizingMaskIntoConstraints = false
        split.addSubview(sidebar)
        split.addSubview(main)
        NSLayoutConstraint.activate([
            sidebar.topAnchor.constraint(equalTo: split.topAnchor),
            sidebar.leadingAnchor.constraint(equalTo: split.leadingAnchor),
            sidebar.bottomAnchor.constraint(equalTo: split.bottomAnchor),
            sidebar.widthAnchor.constraint(equalToConstant: 286),
            main.topAnchor.constraint(equalTo: split.topAnchor),
            main.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            main.trailingAnchor.constraint(equalTo: split.trailingAnchor),
            main.bottomAnchor.constraint(equalTo: split.bottomAnchor),
        ])
        guard let content = window?.contentView else { return }
        split.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(split)
        NSLayoutConstraint.activate([
            split.topAnchor.constraint(equalTo: content.topAnchor),
            split.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            split.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            split.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])

        loadOverviewEditor()
        window?.initialFirstResponder = installButton
        // Focus follows the selection: editing the just-selected agent should
        // not require another click into the role field.
        window?.makeFirstResponder(selected >= 0 ? overviewRoleField : installButton)
    }

    func connectionsPane() -> NSView {
        let mark = symbol("person.3.sequence.fill", description: "Ticky", size: 18, color: Palette.brand)
        let appName = label("Ticky", size: 19, color: .labelColor, weight: .semibold)
        let setup = label("Agent Setup", size: 11)
        let appCopy = NSStackView(views: [appName, setup])
        appCopy.orientation = .vertical
        appCopy.alignment = .leading
        appCopy.spacing = 1
        let brand = NSStackView(views: [mark, appCopy])
        brand.spacing = 10
        brand.alignment = .centerY

        let title = label("Connections", size: 11, color: .secondaryLabelColor, weight: .semibold)
        let codex = backendRow("codex", display: "Codex", symbolName: "terminal")
        let claude = backendRow("claude", display: "Claude Code", symbolName: "text.bubble")
        let privacyIcon = symbol("lock", description: "Private", size: 13)
        let privacyText = wrappingLabel("Credentials stay on this computer.", size: 11, maxLines: 2)
        let privacy = NSStackView(views: [privacyIcon, privacyText])
        privacy.spacing = 8
        privacy.alignment = .centerY

        let stack = NSStackView(views: [brand, title, codex, separator(), claude, NSView(), privacy])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        for view in [brand, codex, claude] { view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true }
        return stack
    }

    func backendRow(_ backend: String, display: String, symbolName: String) -> NSView {
        let state = backendAuthStatus(backend)
        let tint: NSColor = state.ok ? .systemGreen : .systemOrange
        let icon = symbol(symbolName, description: display, size: 16, color: Palette.brand)
        icon.widthAnchor.constraint(equalToConstant: 24).isActive = true

        let name = label(display, size: 13, color: .labelColor, weight: .medium)
        let dot = symbol("circle.fill", description: state.ok ? "Ready" : "Needs attention", size: 7, color: tint)
        let readiness = label(state.ok ? authSummary(backend, state.detail) : state.detail, size: 11,
                              color: state.ok ? .secondaryLabelColor : tint)
        let statusRow = NSStackView(views: [dot, readiness])
        statusRow.spacing = 6
        statusRow.alignment = .centerY
        let copy = NSStackView(views: [name, statusRow])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 3

        let changeImage = NSImage(systemSymbolName: "ellipsis.circle", accessibilityDescription: "Change \(display) connection") ?? NSImage()
        let change = NSButton(image: changeImage, target: self, action: #selector(manageConnection(_:)))
        change.isBordered = false
        change.contentTintColor = .secondaryLabelColor
        change.toolTip = "Change \(display) connection"
        change.setAccessibilityLabel("Change \(display) connection")
        change.tag = backend == "codex" ? 0 : 1
        let row = NSStackView(views: [icon, copy, NSView(), change])
        row.spacing = 9
        row.alignment = .centerY
        row.heightAnchor.constraint(equalToConstant: 60).isActive = true
        return row
    }

    func authSummary(_ backend: String, _ detail: String) -> String {
        if detail.localizedCaseInsensitiveContains("API key") { return "API key stored" }
        if detail.localizedCaseInsensitiveContains("Keychain") { return "Signed in with Keychain" }
        if backend == "codex", detail.localizedCaseInsensitiveContains("subscription") {
            return "Signed in with ChatGPT"
        }
        if detail.localizedCaseInsensitiveContains("subscription") { return "Subscription connected" }
        return detail
    }

    func teamPane() -> NSView {
        let rows = NSStackView()
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 0
        for i in cfg.agents.indices {
            let row = agentOverviewRow(i)
            rows.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: rows.widthAnchor).isActive = true
            if i < cfg.agents.count - 1 {
                let line = separator()
                rows.addArrangedSubview(line)
                line.widthAnchor.constraint(equalTo: rows.widthAnchor).isActive = true
            }
        }

        let group = NSBox()
        group.boxType = .custom
        group.borderWidth = 0
        group.cornerRadius = 12
        group.fillColor = NSColor.controlBackgroundColor.withAlphaComponent(0.62)
        group.contentViewMargins = NSSize(width: 0, height: 0)
        group.contentView = rows

        let add = textButton("Add Agent", action: #selector(addOverviewAgent), tint: Palette.brand)
        add.image = NSImage(systemSymbolName: "plus", accessibilityDescription: "Add agent")
        add.imagePosition = .imageLeading
        add.bezelStyle = .inline

        let stack = NSStackView(views: [group, add])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        group.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        return stack
    }

    func agentOverviewRow(_ index: Int) -> NSView {
        let agent = cfg.agents[index]
        let color = Palette.agent(agent.name, index: index)
        let icon = iconTile(agentSymbol(agent), description: agent.display, symbolSize: 16,
                            tileSize: 38, color: color)

        let name = label(agent.display, size: 15, color: .labelColor, weight: .medium)
        let specialty = wrappingLabel(shortSpecialty(agent), size: 12, maxLines: 1)
        let identity = NSStackView(views: [name, specialty])
        identity.orientation = .vertical
        identity.alignment = .leading
        identity.spacing = 2
        let backend = label(agent.backend, size: 11)

        let enabled = NSButton(checkboxWithTitle: "", target: self, action: #selector(toggleOverviewAgent(_:)))
        enabled.tag = index
        enabled.state = agent.enabled ? .on : .off
        enabled.setAccessibilityLabel("Include \(agent.display)")
        let summary = NSStackView(views: [icon, identity, NSView(), backend, enabled])
        summary.spacing = 10
        summary.alignment = .centerY

        let content = NSStackView(views: [summary])
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 12
        if index == selected {
            content.addArrangedSubview(formRow("Role", overviewRoleField, labelWidth: 76))
            content.addArrangedSubview(formRow("Access", overviewAccessPopup, labelWidth: 76))
        }

        let wrap = AgentRowView()
        wrap.boxType = .custom
        wrap.borderWidth = 0
        wrap.cornerRadius = 9
        wrap.fillColor = index == selected ? color.withAlphaComponent(0.12) : .clear
        wrap.contentView = padded(content, top: 12, side: 14)
        wrap.setAccessibilityLabel("Select \(agent.display)")
        wrap.onSelect = { [weak self] in self?.selectOverviewAgent(index) }
        return wrap
    }

    func agentSymbol(_ agent: AgentCfg) -> String {
        switch agent.name {
        case "rook": return "checkmark.seal"
        case "wren": return "text.book.closed"
        case "finch": return "chevron.left.forwardslash.chevron.right"
        default: return "person.crop.circle"
        }
    }

    func shortSpecialty(_ agent: AgentCfg) -> String {
        // Content-keyed, not name-keyed: an edited role must show the user's
        // words, not the stock label for whoever happens to hold the name.
        if let short = TickyCfg.defaultShortRoles[agent.specialty] { return short }
        let trimmed = agent.specialty.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "No role set yet" }
        let firstSentence = trimmed.split(separator: ".", maxSplits: 1).first.map(String.init) ?? trimmed
        let beforeColon = firstSentence.split(separator: ":", maxSplits: 1).first.map(String.init) ?? firstSentence
        return truncate(beforeColon.trimmingCharacters(in: .whitespaces), 44)
    }

    func loadOverviewEditor() {
        guard selected >= 0, selected < cfg.agents.count else { return }
        overviewOriginalRole = shortSpecialty(cfg.agents[selected])
        overviewRoleField.stringValue = overviewOriginalRole
        overviewAccessPopup.selectItem(withTitle: cfg.agents[selected].access)
    }

    func commitOverviewEditor() {
        guard !showingAdvanced, selected >= 0, selected < cfg.agents.count else { return }
        let role = overviewRoleField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !role.isEmpty, role != overviewOriginalRole { cfg.agents[selected].specialty = role }
        cfg.agents[selected].access = overviewAccessPopup.titleOfSelectedItem ?? cfg.agents[selected].access
        if cfg.agents[selected].access != "workspace-write" || cfg.agents[selected].backend != "codex" {
            cfg.agents[selected].network = false
        }
    }

    func selectOverviewAgent(_ index: Int) {
        guard index >= 0, index < cfg.agents.count, index != selected else { return }
        commitOverviewEditor()
        selected = index
        buildOverviewUI()
    }

    @objc func toggleOverviewAgent(_ sender: NSButton) {
        guard sender.tag >= 0, sender.tag < cfg.agents.count else { return }
        cfg.agents[sender.tag].enabled = sender.state == .on
    }

    @objc func overviewEditorChanged() {
        commitOverviewEditor()
    }

    @objc func addOverviewAgent() {
        commitOverviewEditor()
        var i = 1
        while cfg.agents.contains(where: { $0.name == "agent\(i)" }) { i += 1 }
        cfg.agents.append(.fresh("Agent\(i)", backend: "codex"))
        selected = cfg.agents.count - 1
        buildOverviewUI()
        window?.makeFirstResponder(overviewRoleField)
    }

    @objc func manageConnection(_ sender: NSButton) {
        showAdvancedSettings()
        window?.makeFirstResponder(sender.tag == 0 ? codexKeyField : claudeKeyField)
    }

    @objc func showAdvancedSettings() {
        commitOverviewEditor()
        buildAdvancedUI()
    }

    @objc func showOverview() {
        commitForm()
        cfg.preferences = prefsView.string
        buildOverviewUI()
    }

    // ------------------------------------------------------ advanced screen

    func configureAdvancedControls() {
        guard !advancedConfigured else { return }
        advancedConfigured = true
        let col = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("agent"))
        col.title = "Agents"
        table.addTableColumn(col)
        table.headerView = nil
        table.dataSource = self
        table.delegate = self
        table.rowHeight = 28
        table.style = .sourceList
        table.backgroundColor = .clear
        table.usesAlternatingRowBackgroundColors = false

        backendPopup.addItems(withTitles: ["codex", "claude"])
        backendPopup.target = self
        backendPopup.action = #selector(backendChanged)
        accessPopup.addItems(withTitles: ["read-only", "workspace-write", "full"])
        priorityPopup.addItems(withTitles: ["1 (call first)", "2", "3", "4", "5"])
        modelCombo.completes = true
        toolLabel.font = .monospacedSystemFont(ofSize: 10, weight: .regular)
        toolLabel.textColor = .tertiaryLabelColor
        nameField.delegate = self  // live tool-name preview while typing

        // A programmatic NSTextView needs explicit sizing behavior to wrap and
        // scroll correctly inside an NSScrollView.
        prefsView.font = .systemFont(ofSize: 12)
        prefsView.isRichText = false
        prefsView.isVerticallyResizable = true
        prefsView.isHorizontallyResizable = false
        prefsView.autoresizingMask = [.width]
        prefsView.textContainer?.widthTracksTextView = true
        prefsView.minSize = NSSize(width: 0, height: 54)
        prefsView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude,
                                   height: CGFloat.greatestFiniteMagnitude)
        prefsView.textContainerInset = NSSize(width: 4, height: 6)

        applyButton.target = self
        applyButton.action = #selector(applyAndInstall)
        applyButton.keyEquivalent = "\r"
        applyButton.controlSize = .large
        applyButton.bezelColor = Palette.brand
        applyButton.attributedTitle = brandButtonTitle("Save and Install")

        codexKeyField.widthAnchor.constraint(equalToConstant: 170).isActive = true
        claudeKeyField.widthAnchor.constraint(equalToConstant: 170).isActive = true
        codexStatus.widthAnchor.constraint(equalToConstant: 170).isActive = true
        claudeStatus.widthAnchor.constraint(equalToConstant: 170).isActive = true
        for field in [nameField, timeoutField, specialtyField, noteField] {
            field.widthAnchor.constraint(equalToConstant: 210).isActive = true
        }
        workdirField.widthAnchor.constraint(equalToConstant: 130).isActive = true
        modelCombo.widthAnchor.constraint(equalToConstant: 210).isActive = true
        for popup in [backendPopup, accessPopup, priorityPopup] {
            popup.widthAnchor.constraint(equalToConstant: 160).isActive = true
        }
    }

    func buildAdvancedUI() {
        clearContent()
        showingAdvanced = true
        window?.title = "Advanced Settings"
        configureAdvancedControls()
        refreshAuth()

        let back = NSButton(title: "Team", target: self, action: #selector(showOverview))
        back.image = NSImage(systemSymbolName: "chevron.left", accessibilityDescription: "Back to team")
        back.imagePosition = .imageLeading
        back.bezelStyle = .inline
        let sidebarTitle = label("Agents", size: 17, color: .labelColor, weight: .semibold)

        codexKeyField.placeholderString = "OpenAI API key"
        claudeKeyField.placeholderString = "Anthropic API key"
        let codexRow = NSStackView(views: [
            { let l = label("Codex", size: 12, color: .labelColor, weight: .medium); l.widthAnchor.constraint(equalToConstant: 72).isActive = true; return l }(),
            codexStatus,
            NSButton(title: "Sign In…", target: self, action: #selector(codexLogin)),
            codexKeyField,
            NSButton(title: "Save Key", target: self, action: #selector(saveCodexKey)),
        ])
        let claudeRow = NSStackView(views: [
            { let l = label("Claude", size: 12, color: .labelColor, weight: .medium); l.widthAnchor.constraint(equalToConstant: 72).isActive = true; return l }(),
            claudeStatus,
            NSButton(title: "Sign In…", target: self, action: #selector(claudeLogin)),
            claudeKeyField,
            NSButton(title: "Save Key", target: self, action: #selector(saveClaudeKey)),
        ])
        for row in [codexRow, claudeRow] { row.spacing = 8; row.alignment = .centerY }
        let backendsStack = NSStackView(views: [codexRow, claudeRow])
        backendsStack.orientation = .vertical
        backendsStack.alignment = .leading
        backendsStack.spacing = 8
        let connectionsGroup = settingsGroup("Connections", backendsStack)

        let tableScroll = NSScrollView()
        tableScroll.documentView = table
        tableScroll.hasVerticalScroller = true
        tableScroll.drawsBackground = false
        tableScroll.borderType = .noBorder
        let addRemove = NSSegmentedControl(labels: ["+", "−"], trackingMode: .momentary,
                                           target: self, action: #selector(addRemoveAgent(_:)))
        let sidebarRoot = NSStackView(views: [back, sidebarTitle, tableScroll, addRemove])
        sidebarRoot.orientation = .vertical
        sidebarRoot.alignment = .leading
        sidebarRoot.spacing = 10
        tableScroll.widthAnchor.constraint(equalTo: sidebarRoot.widthAnchor).isActive = true
        // The table is the only flexible view in the sidebar stack; anything
        // higher leaves the layout ambiguous and the scroll view can collapse.
        tableScroll.setContentHuggingPriority(NSLayoutConstraint.Priority(1), for: .vertical)
        tableScroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 120).isActive = true

        let workdirRow = NSStackView(views: [workdirField, NSButton(title: "Choose…", target: self, action: #selector(chooseWorkdir))])
        workdirRow.spacing = 6
        let leftForm = NSStackView(views: [
            formRow("Name", nameField, labelWidth: 62),
            formRow("", toolLabel, labelWidth: 62),
            formRow("Backend", backendPopup, labelWidth: 62),
            formRow("Model", modelCombo, labelWidth: 62),
            formRow("Priority", priorityPopup, labelWidth: 62),
            formRow("", enabledCheck, labelWidth: 62),
        ])
        leftForm.orientation = .vertical
        leftForm.alignment = .leading
        leftForm.spacing = 6
        let rightForm = NSStackView(views: [
            formRow("Access", accessPopup, labelWidth: 62),
            formRow("Workdir", workdirRow, labelWidth: 62),
            formRow("Timeout", timeoutField, labelWidth: 62),
            formRow("Role", specialtyField, labelWidth: 62),
            formRow("Note", noteField, labelWidth: 62),
            formRow("", networkCheck, labelWidth: 62),
        ])
        rightForm.orientation = .vertical
        rightForm.alignment = .leading
        rightForm.spacing = 6
        let agentForms = NSStackView(views: [leftForm, rightForm])
        agentForms.spacing = 18
        agentForms.alignment = .top
        let agentGroup = settingsGroup("Agent Details", agentForms)

        prefsView.string = cfg.preferences
        let prefsScroll = NSScrollView()
        prefsScroll.documentView = prefsView
        prefsScroll.hasVerticalScroller = true
        prefsScroll.borderType = .bezelBorder
        prefsScroll.heightAnchor.constraint(equalToConstant: 54).isActive = true
        let routingGroup = settingsGroup("Routing", prefsScroll)

        let title = label("Advanced Settings", size: 24, color: .labelColor, weight: .semibold)
        let subtitle = label("Connections, permissions, and routing", size: 12)
        let header = NSStackView(views: [title, subtitle])
        header.orientation = .vertical
        header.alignment = .leading
        header.spacing = 3

        let footer = NSStackView(views: [statusLabel, NSView(), applyButton])
        footer.spacing = 8
        footer.alignment = .centerY
        statusLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let mainRoot = NSStackView(views: [header, connectionsGroup, agentGroup, routingGroup, NSView(), footer])
        mainRoot.orientation = .vertical
        mainRoot.alignment = .leading
        mainRoot.spacing = 10

        let sidebar = NSVisualEffectView()
        sidebar.material = .sidebar
        sidebar.blendingMode = .behindWindow
        sidebar.state = .followsWindowActiveState
        sidebarRoot.translatesAutoresizingMaskIntoConstraints = false
        sidebar.addSubview(sidebarRoot)
        NSLayoutConstraint.activate([
            sidebarRoot.topAnchor.constraint(equalTo: sidebar.topAnchor, constant: 18),
            sidebarRoot.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 16),
            sidebarRoot.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -14),
            sidebarRoot.bottomAnchor.constraint(equalTo: sidebar.bottomAnchor, constant: -16),
        ])

        let main = NSVisualEffectView()
        main.material = .contentBackground
        main.blendingMode = .withinWindow
        main.state = .followsWindowActiveState
        mainRoot.translatesAutoresizingMaskIntoConstraints = false
        main.addSubview(mainRoot)
        NSLayoutConstraint.activate([
            mainRoot.topAnchor.constraint(equalTo: main.topAnchor, constant: 20),
            mainRoot.leadingAnchor.constraint(equalTo: main.leadingAnchor, constant: 24),
            mainRoot.trailingAnchor.constraint(equalTo: main.trailingAnchor, constant: -24),
            mainRoot.bottomAnchor.constraint(equalTo: main.bottomAnchor, constant: -18),
        ])
        for view in [header, connectionsGroup, agentGroup, routingGroup, footer] {
            view.widthAnchor.constraint(equalTo: mainRoot.widthAnchor).isActive = true
        }

        let split = NSView()
        sidebar.translatesAutoresizingMaskIntoConstraints = false
        main.translatesAutoresizingMaskIntoConstraints = false
        split.addSubview(sidebar)
        split.addSubview(main)
        NSLayoutConstraint.activate([
            sidebar.topAnchor.constraint(equalTo: split.topAnchor),
            sidebar.leadingAnchor.constraint(equalTo: split.leadingAnchor),
            sidebar.bottomAnchor.constraint(equalTo: split.bottomAnchor),
            sidebar.widthAnchor.constraint(equalToConstant: 220),
            main.topAnchor.constraint(equalTo: split.topAnchor),
            main.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            main.trailingAnchor.constraint(equalTo: split.trailingAnchor),
            main.bottomAnchor.constraint(equalTo: split.bottomAnchor),
        ])
        guard let content = window?.contentView else { return }
        split.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(split)
        NSLayoutConstraint.activate([
            split.topAnchor.constraint(equalTo: content.topAnchor),
            split.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            split.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            split.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])

        reloadKeepingSelection()
        if !cfg.agents.isEmpty { selectRow(min(max(selected, 0), cfg.agents.count - 1)) }
    }

    func settingsGroup(_ title: String, _ content: NSView) -> NSStackView {
        let heading = label(title, size: 12, color: .secondaryLabelColor, weight: .medium)
        let box = NSBox()
        box.boxType = .custom
        box.borderWidth = 0
        box.cornerRadius = 10
        box.fillColor = NSColor.controlBackgroundColor.withAlphaComponent(0.62)
        box.contentView = padded(content, top: 10, side: 12)
        let stack = NSStackView(views: [heading, box])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 5
        box.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        return stack
    }

    func padded(_ view: NSView, top: CGFloat = 8, side: CGFloat = 8) -> NSView {
        let wrap = NSView()
        view.translatesAutoresizingMaskIntoConstraints = false
        wrap.addSubview(view)
        NSLayoutConstraint.activate([
            view.topAnchor.constraint(equalTo: wrap.topAnchor, constant: top),
            view.leadingAnchor.constraint(equalTo: wrap.leadingAnchor, constant: side),
            view.trailingAnchor.constraint(equalTo: wrap.trailingAnchor, constant: -side),
            view.bottomAnchor.constraint(equalTo: wrap.bottomAnchor, constant: -top),
        ])
        return wrap
    }

    // --- backends actions

    func refreshAuth() {
        let c = backendAuthStatus("codex")
        codexStatus.stringValue = c.ok ? "Connected" : c.detail
        codexStatus.textColor = c.ok ? .systemGreen : .systemOrange
        codexStatus.toolTip = c.detail
        let a = backendAuthStatus("claude")
        claudeStatus.stringValue = a.ok ? "Connected" : a.detail
        claudeStatus.textColor = a.ok ? .systemGreen : .systemOrange
        claudeStatus.toolTip = a.detail
    }

    @objc func codexLogin() {
        openTerminal(running: "codex login")
        statusLabel.stringValue = "finish the ChatGPT login in Terminal, then reopen setup to refresh"
    }

    @objc func claudeLogin() {
        openTerminal(running: "claude auth login")
        statusLabel.stringValue = "finish the Anthropic login in Terminal, then reopen setup to refresh"
    }

    @objc func saveCodexKey() { saveKey("OPENAI_API_KEY", codexKeyField) }
    @objc func saveClaudeKey() { saveKey("ANTHROPIC_API_KEY", claudeKeyField) }

    func saveKey(_ name: String, _ field: NSSecureTextField) {
        let v = field.stringValue.trimmingCharacters(in: .whitespaces)
        guard !v.isEmpty else { statusLabel.stringValue = "empty key, nothing saved"; return }
        do {
            try saveEnvKey(name, v)
            field.stringValue = ""
            statusLabel.stringValue = "\(name) saved to ~/.ticky/env (0600)"
            refreshAuth()
        } catch {
            statusLabel.stringValue = "could not save key: \(error.localizedDescription)"
        }
    }

    // --- agents table

    func numberOfRows(in tableView: NSTableView) -> Int { cfg.agents.count }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let a = cfg.agents[row]
        let cell = NSTextField(labelWithString: "")
        cell.font = .systemFont(ofSize: 12)
        let text = "\(a.display)  ·  \(a.backend) p\(a.priority)" + (a.enabled ? "" : "  (off)")
        let title = NSMutableAttributedString(string: "● ", attributes: [
            .foregroundColor: a.enabled ? Palette.agent(a.name, index: row) : NSColor.tertiaryLabelColor,
            .font: NSFont.systemFont(ofSize: 9),
            .baselineOffset: 1,
        ])
        title.append(NSAttributedString(string: text, attributes: [
            .foregroundColor: a.enabled ? NSColor.labelColor : .tertiaryLabelColor,
            .font: NSFont.systemFont(ofSize: 12),
        ]))
        cell.attributedStringValue = title
        return cell
    }

    func tableViewSelectionDidChange(_ notification: Notification) {
        if suppressSelectionCallback { return }
        commitForm()  // commit the row being left before loading the new one
        selected = table.selectedRow
        loadForm()
    }

    func selectRow(_ i: Int) {
        suppressSelectionCallback = true
        table.selectRowIndexes(IndexSet(integer: i), byExtendingSelection: false)
        suppressSelectionCallback = false
        selected = i
        loadForm()
    }

    func reloadKeepingSelection() {
        suppressSelectionCallback = true
        table.reloadData()
        if selected >= 0, selected < cfg.agents.count {
            table.selectRowIndexes(IndexSet(integer: selected), byExtendingSelection: false)
        }
        suppressSelectionCallback = false
    }

    @objc func addRemoveAgent(_ sender: NSSegmentedControl) {
        commitForm()
        if sender.selectedSegment == 0 {
            var i = 1
            while cfg.agents.contains(where: { $0.name == "agent\(i)" }) { i += 1 }
            cfg.agents.append(.fresh("Agent\(i)", backend: "codex"))
            reloadKeepingSelection()
            selectRow(cfg.agents.count - 1)
            window?.makeFirstResponder(nameField)
        } else if selected >= 0 && cfg.agents.count > 1 {
            cfg.agents.remove(at: selected)
            reloadKeepingSelection()
            selectRow(min(selected, cfg.agents.count - 1))
        }
    }

    // --- agent form

    func modelSuggestions(for backend: String) -> [String] {
        backend == "codex" ? ["gpt-5.5", "gpt-5.5-codex"] : ["opus", "sonnet", "haiku"]
    }

    @objc func backendChanged() {
        modelCombo.removeAllItems()
        modelCombo.addItems(withObjectValues: modelSuggestions(for: backendPopup.titleOfSelectedItem ?? "codex"))
    }

    func controlTextDidChange(_ obj: Notification) {
        if (obj.object as? NSTextField) === nameField {
            toolLabel.stringValue = "tool: ask_" + slug(nameField.stringValue)
        }
    }

    func slug(_ s: String) -> String {
        String(s.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) })
    }

    @objc func chooseWorkdir() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.directoryURL = URL(fileURLWithPath: NSString(string: workdirField.stringValue).expandingTildeInPath)
        if panel.runModal() == .OK, let url = panel.url {
            var p = url.path
            if p.hasPrefix(home) { p = "~" + p.dropFirst(home.count) }
            workdirField.stringValue = p
        }
    }

    func loadForm() {
        guard selected >= 0, selected < cfg.agents.count else { return }
        let a = cfg.agents[selected]
        nameField.stringValue = a.display
        toolLabel.stringValue = "tool: ask_" + a.name
        backendPopup.selectItem(withTitle: a.backend)
        backendChanged()
        modelCombo.stringValue = a.model ?? ""
        accessPopup.selectItem(withTitle: a.access)
        priorityPopup.selectItem(at: max(0, min(4, a.priority - 1)))
        workdirField.stringValue = a.workdir
        timeoutField.stringValue = String(a.timeout)
        specialtyField.stringValue = a.specialty
        noteField.stringValue = a.routing_note
        enabledCheck.state = a.enabled ? .on : .off
        networkCheck.state = a.network ? .on : .off
    }

    func commitForm() {
        guard selected >= 0, selected < cfg.agents.count else { return }
        var a = cfg.agents[selected]
        let display = nameField.stringValue.trimmingCharacters(in: .whitespaces)
        if !display.isEmpty { a.display = display; a.name = slug(display) }
        a.backend = backendPopup.titleOfSelectedItem ?? a.backend
        let m = modelCombo.stringValue.trimmingCharacters(in: .whitespaces)
        a.model = m.isEmpty ? nil : m
        a.access = accessPopup.titleOfSelectedItem ?? a.access
        a.priority = priorityPopup.indexOfSelectedItem + 1
        a.workdir = workdirField.stringValue.isEmpty ? "~" : workdirField.stringValue
        a.timeout = max(1, Int(timeoutField.stringValue) ?? a.timeout)
        a.specialty = specialtyField.stringValue
        a.routing_note = noteField.stringValue
        a.enabled = enabledCheck.state == .on
        a.network = networkCheck.state == .on && a.backend == "codex" && a.access == "workspace-write"
        cfg.agents[selected] = a
        // AppKit can still emit a selection notification for a row-only reload.
        // Suppress it so committing one row cannot recurse until the stack overflows.
        suppressSelectionCallback = true
        table.reloadData(forRowIndexes: IndexSet(integer: selected),
                         columnIndexes: IndexSet(integer: 0))
        suppressSelectionCallback = false
    }

    // --- save and install

    func validationError() -> String? {
        let names = cfg.agents.map { $0.name }
        if names.contains("") || Set(names).count != names.count {
            return "Agent names must be non-empty and unique."
        }
        if !cfg.agents.contains(where: { $0.enabled }) {
            return "Keep at least one agent enabled."
        }
        return nil
    }

    func setInstallBusy(_ busy: Bool) {
        installButton.isEnabled = !busy
        applyButton.isEnabled = !busy
    }

    func saveAndInstall() {
        if let error = validationError() {
            statusLabel.stringValue = error
            return
        }
        do {
            try cfg.save()
        } catch {
            statusLabel.stringValue = "Could not write config: \(error.localizedDescription)"
            return
        }

        statusLabel.stringValue = "Saving and installing into Claude Code and Codex…"
        setInstallBusy(true)
        let cli = tickyCli()
        DispatchQueue.global().async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: cli)
            process.arguments = ["install", "all"]
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            var result = "Install failed to run."
            do {
                try process.run()
                process.waitUntilExit()
                let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                result = process.terminationStatus == 0
                    ? "Team installed. Restart active Claude Code or Codex sessions to refresh it."
                    : "Install error: " + out.trimmingCharacters(in: .whitespacesAndNewlines)
            } catch {
                result = "Could not run \(cli): \(error.localizedDescription)"
            }
            DispatchQueue.main.async {
                self.statusLabel.stringValue = result
                self.setInstallBusy(false)
            }
        }
    }

    @objc func installTeam() {
        commitOverviewEditor()
        saveAndInstall()
    }

    @objc func applyAndInstall() {
        commitForm()
        cfg.preferences = prefsView.string
        saveAndInstall()
    }

    func reloadFromDisk() {
        cfg = TickyCfg.load() ?? cfg
        refreshAuth()
        if showingAdvanced {
            reloadKeepingSelection()
            if !cfg.agents.isEmpty { selectRow(min(max(selected, 0), cfg.agents.count - 1)) }
        } else {
            buildOverviewUI()
        }
    }

    func windowWillClose(_ notification: Notification) {
        // Closing should not silently discard edits: commit whatever pane is
        // open and persist if the roster is valid. Installing into bosses
        // stays behind the explicit button.
        if showingAdvanced {
            commitForm()
            cfg.preferences = prefsView.string
        } else {
            commitOverviewEditor()
        }
        if validationError() == nil { try? cfg.save() }
    }
}

// ------------------------------------------------------------ menu bar app

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!
    let menu = NSMenu()
    var setup: SetupWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        menu.delegate = self
        menu.autoenablesItems = false
        statusItem.menu = menu
        updateButton()
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.updateButton()
            self?.checkSetupFlag()
        }
        RunLoop.main.add(timer, forMode: .common)
        if !FileManager.default.fileExists(atPath: configPath) {
            openSetup()  // first run: config does not exist yet
        }
    }

    func checkSetupFlag() {
        if FileManager.default.fileExists(atPath: setupFlagPath) {
            try? FileManager.default.removeItem(atPath: setupFlagPath)
            openSetup()
        }
    }

    @objc func openSetup() {
        if setup == nil || setup?.window == nil {
            setup = SetupWindowController()
        } else if let s = setup {
            s.reloadFromDisk()
        }
        NSApp.activate(ignoringOtherApps: true)
        setup?.showWindow(nil)
        setup?.window?.makeKeyAndOrderFront(nil)
    }

    func statusSymbol(_ name: String, description: String) -> NSImage? {
        let config = NSImage.SymbolConfiguration(pointSize: 13, weight: .medium)
        let image = NSImage(systemSymbolName: name, accessibilityDescription: description)?
            .withSymbolConfiguration(config)
        image?.isTemplate = true  // adapts to menu bar appearance automatically
        return image
    }

    func updateButton() {
        guard let button = statusItem.button else { return }
        let running = readState()
        if running.isEmpty {
            button.image = statusSymbol("person.3.fill", description: "Ticky idle")
            button.imagePosition = .imageOnly
            button.attributedTitle = NSAttributedString(string: "")
            button.toolTip = "ticky · idle"
        } else {
            button.image = statusSymbol("person.3.sequence.fill", description: "Ticky working")
            button.imagePosition = .imageLeading
            button.attributedTitle = NSAttributedString(string: " \(running.count)", attributes: [
                .foregroundColor: Palette.brand,
                .font: NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold),
            ])
            button.toolTip = "ticky working\n" + running.map { "\($0.agent): \($0.reason)" }.joined(separator: "\n")
        }
    }

    func infoItem(_ title: String, color: NSColor, body: String) -> NSMenuItem {
        let item = NSMenuItem(title: "", action: #selector(openLogFile), keyEquivalent: "")
        item.target = self
        let text = NSMutableAttributedString(string: title, attributes: [
            .foregroundColor: color,
            .font: NSFont.systemFont(ofSize: 13),
        ])
        text.append(NSAttributedString(string: body, attributes: [
            .foregroundColor: NSColor.labelColor,
            .font: NSFont.systemFont(ofSize: 13),
        ]))
        item.attributedTitle = text
        return item
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let entries = readLogTail(10)
        let nAgents = (TickyCfg.load()?.agents.filter { $0.enabled }.count) ?? 0
        let header = NSMenuItem(title: "Ticky · \(nAgents) agents · \(callsToday()) calls today",
                                action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(.separator())

        let running = readState()
        if !running.isEmpty {
            for r in running {
                let item = infoItem("● ", color: Palette.brand,
                                    body: "\(r.agent) working (\(elapsed(r.started))): \(truncate(r.reason, 48))")
                item.toolTip = r.reason
                menu.addItem(item)
            }
            menu.addItem(.separator())
        }

        if entries.isEmpty {
            let item = NSMenuItem(title: "No calls logged yet", action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        } else {
            for e in entries {
                let ok = e.status == "ok"
                let item = infoItem(ok ? "✓ " : "✗ ", color: ok ? .systemGreen : .systemRed,
                                    body: "\(e.agent) · \(relative(e.ts)) · \(Int(e.duration))s · \(truncate(e.reason, 44))")
                item.toolTip = "boss: \(e.boss)\nreason: \(e.reason)\nstatus: \(e.status)"
                menu.addItem(item)
            }
        }
        menu.addItem(.separator())

        let setupItem = NSMenuItem(title: "Ticky Setup…", action: #selector(openSetup), keyEquivalent: ",")
        setupItem.target = self
        menu.addItem(setupItem)
        let openLog = NSMenuItem(title: "Open Call Log", action: #selector(openLogFile), keyEquivalent: "l")
        openLog.target = self
        menu.addItem(openLog)
        let openCfg = NSMenuItem(title: "Reveal Config in Finder", action: #selector(revealConfig), keyEquivalent: "")
        openCfg.target = self
        menu.addItem(openCfg)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Ticky",
                              action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)
    }

    @objc func openLogFile() {
        if FileManager.default.fileExists(atPath: logPath) {
            NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
        } else {
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: tickyHome)])
        }
    }

    @objc func revealConfig() {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: configPath)])
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
