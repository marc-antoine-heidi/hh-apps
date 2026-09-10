import DesignSystem
import SwiftUI
import UIKit

@MainActor
enum NativeExporter {
    static func export(window: UIWindow) async throws {
        let output = URL.documentsDirectory.appending(path: "ios-export", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        try exportTokens().write(to: output.appending(path: "tokens.json"))
        var records: [[String: Any]] = []
        let configurations: [(String, ColorScheme, DynamicTypeSize, LayoutDirection, CGFloat)] = [
            ("light", .light, .large, .leftToRight, 390),
            ("dark", .dark, .large, .leftToRight, 390),
            ("large-text", .light, .accessibility1, .leftToRight, 390),
            ("rtl", .light, .large, .rightToLeft, 390),
            ("wide", .light, .large, .leftToRight, 768),
        ]
        for (configuration, scheme, textSize, direction, width) in configurations {
            for sample in previewSamples() + typographySamples() + accentShadowSamples() {
                var height = textSize.isAccessibilitySize ? sample.height * 2.5 : sample.height
                let content = sample.content
                    .hhTextStyle(.p1)
                    .foregroundStyle(HHColors.foregroundPrimary.color)
                    .frame(width: width, alignment: .top)
                    .background(HHColors.surfacePrimary.color)
                    .environment(\.colorScheme, scheme)
                    .environment(\.dynamicTypeSize, textSize)
                    .environment(\.layoutDirection, direction)
                    .environment(\.locale, Locale(identifier: direction == .rightToLeft ? "ar" : "en_AU"))
                let host = UIHostingController(rootView: content)
                host.safeAreaRegions = []
                if sample.fitsContent {
                    height = ceil(host.sizeThatFits(in: CGSize(width: width, height: 10000)).height)
                    guard height > 0 && height < 10000 else {
                        throw NSError(domain: "NativePreview", code: 1, userInfo: [NSLocalizedDescriptionKey: "Specimen requires explicit bounds: \(sample.id)"])
                    }
                }
                host.overrideUserInterfaceStyle = scheme == .dark ? .dark : .light
                window.overrideUserInterfaceStyle = host.overrideUserInterfaceStyle
                window.frame = CGRect(x: 0, y: 0, width: width, height: height)
                window.rootViewController = host
                host.view.frame = window.bounds
                host.view.backgroundColor = HHColors.surfacePrimary.uiColor
                host.view.setNeedsLayout()
                host.view.layoutIfNeeded()
                try await Task.sleep(for: .milliseconds(350))
                let format = UIGraphicsImageRendererFormat()
                format.scale = 2
                format.opaque = true
                let renderer = UIGraphicsImageRenderer(bounds: host.view.bounds, format: format)
                var didDraw = false
                let image = renderer.image { _ in
                    didDraw = host.view.drawHierarchy(in: host.view.bounds, afterScreenUpdates: true)
                }
                guard didDraw else { throw NSError(domain: "NativePreview", code: 2, userInfo: [NSLocalizedDescriptionKey: "Capture failed: \(sample.id)"]) }
                guard let data = image.pngData() else { throw CocoaError(.fileWriteUnknown) }
                let filename = "\(sample.id)-\(configuration).png"
                try data.write(to: output.appending(path: filename))
                records.append([
                    "id": sample.id, "title": sample.title, "components": sample.components,
                    "configuration": configuration, "file": filename, "width": width, "height": height,
                    "scale": 2, "colorScheme": scheme == .dark ? "dark" : "light",
                ])
            }
        }
        let manifest: [String: Any] = [
            "previews": records, "osVersion": UIDevice.current.systemVersion,
            "device": UIDevice.current.model, "renderer": "UIHostingController.drawHierarchy", "syntheticContent": true,
        ]
        try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
            .write(to: output.appending(path: "complete.json"), options: .atomic)
    }
}
