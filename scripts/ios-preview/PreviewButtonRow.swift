import DesignSystem
import SwiftUI

struct PreviewButtonRow<Content: View>: View {
    @Environment(\.dynamicTypeSize)
    private var textSize
    @ViewBuilder
    let content: () -> Content

    var body: some View {
        if textSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: HHSpacing.space2, content: content)
        } else {
            HStack(spacing: HHSpacing.space2, content: content)
        }
    }
}
