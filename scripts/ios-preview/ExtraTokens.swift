import DesignSystem
import UIKit

@MainActor
func extraTokens() -> [String: Any] {
    func pair(_ color: HHColorPair) -> [String: Any] {
        ["light": color.light, "dark": color.dark, "lightAlpha": color.lightAlpha, "darkAlpha": color.darkAlpha]
    }
    let traits = UITraitCollection(preferredContentSizeCategory: .large)
    return [
        "HHAccentHue": Dictionary(
            uniqueKeysWithValues: HHAccentHue.allCases.map { hue in
                (String(describing: hue), ["foreground": pair(hue.foreground), "background": pair(hue.background)])
            }
        ),
        "SettingsRowMetrics": [
            "leadingIconSize": SettingsRowMetrics.leadingIconSize,
            "leadingIconTitleSpacing": SettingsRowMetrics.leadingIconTitleSpacing,
            "titleSubtitleSpacing": SettingsRowMetrics.titleSubtitleSpacing,
        ],
        "SettingsListLayout": [
            "sectionSpacing": SettingsListLayout.sectionSpacing,
            "rootTopContentMargin": SettingsListLayout.rootTopContentMargin,
        ],
        "HHMarkdownMetrics": ["italicObliqueness": HHMarkdownTextStyle.italicObliqueness],
        "HHMarkdownBlockStyle": Dictionary(
            uniqueKeysWithValues: [HHMarkdownBlockStyle.paragraph, .h1, .h2, .h3]
                .map { style in
                    let spacing = style.scaledSpacing(compatibleWith: traits)
                    return (
                        String(describing: style),
                        [
                            "before": spacing.before.map { $0 as Any } ?? NSNull(),
                            "after": spacing.after.map { $0 as Any } ?? NSNull(),
                        ],
                    )
                }
        ),
        "HeidiShadowStyle": Dictionary(
            uniqueKeysWithValues: shadowTokens()
                .map { name, style in
                    var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
                    UIColor(style.color).resolvedColor(with: UITraitCollection(userInterfaceStyle: .light)).getRed(&r, green: &g, blue: &b, alpha: &a)
                    return (
                        name,
                        [
                            "xOffset": style.xOffset, "yOffset": style.yOffset, "radius": style.radius,
                            "red": r, "green": g, "blue": b, "alpha": a,
                        ],
                    )
                }
        ),
    ]
}
