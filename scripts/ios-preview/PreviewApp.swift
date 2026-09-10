import ComponentsKit
import DesignSystem
import SwiftUI
import UIKit

@main
@MainActor
final class PreviewApp: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        Theme.current = .heidi
        NativeChromeTypography.apply()
        let window = UIWindow(frame: UIScreen.main.bounds)
        self.window = window
        window.rootViewController = UIHostingController(rootView: Text(verbatim: "Preparing native previews"))
        window.makeKeyAndVisible()
        Task { @MainActor in
            do {
                try await NativeExporter.export(window: window)
                window.rootViewController = UIHostingController(rootView: Text(verbatim: "Native preview export complete").accessibilityIdentifier("export-complete"))
            } catch {
                window.rootViewController = UIHostingController(rootView: Text(verbatim: "Export failed: \(error)").accessibilityIdentifier("export-failed"))
            }
        }
        return true
    }
}
