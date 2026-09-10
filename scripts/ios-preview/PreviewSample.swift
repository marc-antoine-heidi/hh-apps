import SwiftUI

struct PreviewSample {
    let id: String
    let title: String
    let components: [String]
    let height: CGFloat
    let fitsContent: Bool
    let content: AnyView

    init(_ id: String, _ title: String, components: [String], height: CGFloat = 700, fitsContent: Bool = true, @ViewBuilder content: () -> some View) {
        self.id = id
        self.title = title
        self.components = components
        self.height = height
        self.fitsContent = fitsContent
        self.content = AnyView(content())
    }
}
