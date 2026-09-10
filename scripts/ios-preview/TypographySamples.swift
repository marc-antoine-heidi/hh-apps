import DesignSystem
import SwiftUI

@MainActor
func typographySamples() -> [PreviewSample] {
    var samples = HHTextStyle.allCases.map { style in
        PreviewSample("type-\(style)", "HHTextStyle.\(style)", components: [], height: 320) {
            VStack(alignment: .leading, spacing: HHSpacing.space4) {
                Text(verbatim: "The quick brown fox").hhTextStyle(style)
                Text(verbatim: "Care begins with a conversation. This is a multiline text specimen.").hhTextStyle(style)
            }
            .frame(maxWidth: .infinity, alignment: .leading).padding(HHSpacing.space4)
        }
    }
    samples += HHMarkdownTextStyle.allCases.map { style in
        PreviewSample("type-markdown-\(style)", "HHMarkdownTextStyle.\(style)", components: [], height: 350) {
            Text(verbatim: "Care begins with a conversation. This is a multiline Markdown text specimen.")
                .hhMarkdownTextStyle(style)
                .padding(HHSpacing.space4)
        }
    }
    samples.append(
        PreviewSample("type-exceptions", "HHFont named exceptions", components: [], height: 420) {
            VStack(alignment: .leading, spacing: HHSpacing.space6) {
                Text(verbatim: "let example = true").font(HHFont.code)
                Text(verbatim: "✨").font(HHFont.emoji)
                Text(verbatim: "AB").font(HHFont.avatarInitials(forAvatarSize: HHSizing.avatarMedium))
                Image(systemName: "plus").font(HHFont.symbol(size: HHSizing.iconLarge))
                Text(verbatim: "Heidi").hhSignInWordmarkStyle(size: HHSizing.signInLogoHeight)
                Text(
                    verbatim:
                        "\(HHMarkdownUnorderedListMarker.topLevel) Top level\n\(HHMarkdownUnorderedListMarker.secondLevel) Second level\n\(HHMarkdownUnorderedListMarker.thirdLevel) Third level"
                )
                .hhTextStyle(.p1)
            }
            .padding(HHSpacing.space4)
        }
    )
    return samples
}
