import DesignSystem
import SwiftUI

@MainActor
func accentShadowSamples() -> [PreviewSample] {
    [
        PreviewSample("accent-hues", "Avatar and chip accent hues", components: [], height: 430) {
            VStack(alignment: .leading, spacing: HHSpacing.space4) {
                ForEach(HHAccentHue.allCases, id: \.self) { hue in
                    Text(verbatim: String(describing: hue))
                        .hhTextStyle(.p1Bold)
                        .foregroundStyle(hue.foreground.color)
                        .padding(HHSpacing.space4)
                        .background(hue.background.color, in: Capsule())
                }
            }
            .padding(HHSpacing.space6)
        },
        PreviewSample("shadows", "Elevation and shadows", components: [], height: 800) {
            VStack(spacing: HHSpacing.space8) {
                ForEach(shadowTokens(), id: \.0) { name, style in
                    Text(verbatim: name)
                        .hhTextStyle(.p1)
                        .frame(maxWidth: .infinity)
                        .padding(HHSpacing.space4)
                        .background(HHColors.surfaceTertiary.color, in: RoundedRectangle(cornerRadius: HHRadius.lg))
                        .heidiShadow(style)
                }
            }
            .padding(HHSpacing.space8)
        },
    ]
}
