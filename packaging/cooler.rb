cask "cooler" do
  version "1.0.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/chetangoel01/cooler/releases/download/v#{version}/Cooler-#{version}.dmg"
  name "Cooler"
  desc "Fan curves and menu bar temperatures for the 16-inch M1 Max MacBook Pro"
  homepage "https://github.com/chetangoel01/cooler"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on cask: "swiftbar"
  depends_on formula: "python"
  depends_on macos: :sonoma

  app "Cooler.app"

  # Steps run with a temporary HOME, so user paths use the :home base, never "~".
  postflight_steps do
    # Installs or upgrades the root controller, keeping the selected profile.
    run "{{appdir}}/Cooler.app/Contents/Resources/install-daemon.sh", sudo: true
    mkdir_p "Library/Application Support/SwiftBar/Plugins", base: :home
    mkdir_p "Library/LaunchAgents", base: :home
    copy "{{appdir}}/Cooler.app/Contents/Resources/cooler.5s.py",
         "Library/Application Support/SwiftBar/Plugins/cooler.5s.py", target_base: :home
    set_permissions "Library/Application Support/SwiftBar/Plugins/cooler.5s.py", "0755",
                    base: :home, recursive: false
    copy "{{appdir}}/Cooler.app/Contents/Resources/com.chetangoel.cooler-monitor.plist",
         "Library/LaunchAgents/com.chetangoel.cooler-monitor.plist", target_base: :home
    # The editor lived here before it became Cooler.app.
    remove "Library/Application Support/Cooler/Cooler Curves.app", base: :home, recursive: true
  end

  uninstall_postflight_steps do
    remove ["Library/Application Support/SwiftBar/Plugins/cooler.5s.py",
            "Library/LaunchAgents/com.chetangoel.cooler-monitor.plist"], base: :home
  end

  # Homebrew also runs this before every upgrade; uninstall.sh keeps the profile.
  uninstall launchctl: "com.chetangoel.cooler",
            script:    {
              executable:   "/Library/Application Support/Cooler/uninstall.sh",
              sudo:         true,
              must_succeed: false,
            }

  zap delete: [
        "/Library/Application Support/Cooler",
        "/var/log/cooler.log",
      ],
      trash:  [
        "~/Library/Application Support/Cooler",
        "~/Library/Caches/CoolerMonitor",
      ]

  caveats <<~EOS
    Cooler controls the fans only on a MacBookPro18,4 (16-inch MacBook Pro, M1 Max).
    SwiftBar should use ~/Library/Application Support/SwiftBar/Plugins as its plugin folder.
  EOS
end
