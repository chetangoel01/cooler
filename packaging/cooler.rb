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
  depends_on macos: :sonoma
  depends_on cask: "swiftbar"
  depends_on formula: "python"

  app "Cooler.app"

  postflight do
    resources = "#{appdir}/Cooler.app/Contents/Resources"
    # Installs or upgrades the root controller, keeping the selected profile.
    system_command "#{resources}/install-daemon.sh", sudo: true
    plugins = Pathname("~/Library/Application Support/SwiftBar/Plugins").expand_path
    agents = Pathname("~/Library/LaunchAgents").expand_path
    [plugins, agents].each(&:mkpath)
    FileUtils.install "#{resources}/cooler.5s.py", plugins/"cooler.5s.py", mode: 0755
    FileUtils.install "#{resources}/com.chetangoel.cooler-monitor.plist",
                      agents/"com.chetangoel.cooler-monitor.plist", mode: 0644
    # The editor lived here before it became Cooler.app.
    FileUtils.rm_rf Pathname("~/Library/Application Support/Cooler/Cooler Curves.app").expand_path
  end

  # Homebrew also runs this before every upgrade; uninstall.sh keeps the profile.
  uninstall launchctl: "com.chetangoel.cooler",
            script:    {
              executable:   "/Library/Application Support/Cooler/uninstall.sh",
              sudo:         true,
              must_succeed: false,
            }

  uninstall_postflight do
    FileUtils.rm_f Pathname("~/Library/Application Support/SwiftBar/Plugins/cooler.5s.py").expand_path
    FileUtils.rm_f Pathname("~/Library/LaunchAgents/com.chetangoel.cooler-monitor.plist").expand_path
  end

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
