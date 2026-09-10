import DesignSystem
import SwiftUI

@MainActor
func previewSamples() -> [PreviewSample] {
    var samples: [PreviewSample] = []
    for variant in HHButtonVariant.allCases {
        samples.append(
            PreviewSample("button-\(variant)", "HHButton · \(variant)", components: ["HHButton", "HHButtonStyle", "HHButtonLoadingIndicator"], height: 720) {
                VStack(alignment: .leading, spacing: HHSpacing.space4) {
                    ForEach(Array(HHSize.allCases.enumerated()), id: \.offset) { _, size in
                        Text(verbatim: "\(size) · \(Int(size.dimension))pt minimum").hhTextStyle(.caption)
                        PreviewButtonRow {
                            ForEach(Array(HHButtonTone.allCases.enumerated()), id: \.offset) { _, tone in
                                HHButton(title: Text(verbatim: String(describing: tone)), variant: variant, size: size, tone: tone) {}
                            }
                        }
                    }
                    HHButton(title: Text(verbatim: "Disabled"), variant: variant) {}.disabled(true)
                    HHButton(title: Text(verbatim: "Loading"), variant: variant, isLoading: true) {}
                    HStack(spacing: HHSpacing.space2) {
                        HHButton(title: Text(verbatim: "Add"), icon: Image(systemName: "plus"), variant: variant) {}
                        HHButton(title: Text(verbatim: "Add"), icon: Image(systemName: "plus"), iconOnly: true, variant: variant) {}
                    }
                    HHButton(title: Text(verbatim: "A longer action label that wraps onto multiple lines"), variant: variant, fillsWidth: true) {}
                }
                .padding(HHSpacing.space4)
            }
        )
    }
    samples.append(
        PreviewSample(
            "legacy-buttons",
            "Existing button families",
            components: [
                "HHSecondaryButton", "HHTertiaryButton", "HeidiPrimaryButtonStyle", "HeidiSecondaryButtonStyle", "HeidiTertiaryButtonStyle", "HeidiPrimaryCapsuleButtonStyle",
                "HeidiSecondaryCapsuleButtonStyle",
            ],
            height: 760,
        ) {
            VStack(spacing: HHSpacing.space4) {
                HHSecondaryButton(title: "Compact secondary", icon: "plus", size: .s) {}
                HHSecondaryButton(title: "Large secondary", size: .l) {}
                HHSecondaryButton(title: "Loading", size: .l, isLoading: true) {}
                HHTertiaryButton(title: "Tertiary", size: .l) {}
                HHTertiaryButton(title: "Compact tertiary", size: .s) {}
                Button {
                } label: {
                    Text(verbatim: "Primary style")
                }
                .buttonStyle(HeidiPrimaryButtonStyle())
                Button {
                } label: {
                    Text(verbatim: "Secondary style")
                }
                .buttonStyle(HeidiSecondaryButtonStyle())
                Button {
                } label: {
                    Text(verbatim: "Tertiary style")
                }
                .buttonStyle(HeidiTertiaryButtonStyle())
                Button {
                } label: {
                    Text(verbatim: "Primary capsule")
                }
                .buttonStyle(HeidiPrimaryCapsuleButtonStyle())
                Button {
                } label: {
                    Text(verbatim: "Secondary capsule")
                }
                .buttonStyle(HeidiSecondaryCapsuleButtonStyle())
            }
            .padding(HHSpacing.space4)
        }
    )
    samples.append(
        PreviewSample("toggle", "HeidiToggle", components: ["HeidiToggle"], height: 330) {
            VStack(spacing: HHSpacing.space6) {
                HeidiToggle(isOn: .constant(true)) { Text(verbatim: "Enabled · on") }
                HeidiToggle(isOn: .constant(false)) { Text(verbatim: "Enabled · off") }
                HeidiToggle(isOn: .constant(true)) { Text(verbatim: "Disabled · on") }.disabled(true)
                HeidiToggle(isOn: .constant(false)) { Text(verbatim: "Disabled · off") }.disabled(true)
            }
            .padding(HHSpacing.space4)
        }
    )
    samples.append(
        PreviewSample(
            "feedback",
            "Alerts, banner and Pro indicator",
            components: ["HHAlert", "HHOfflineBanner", "ProFeatureIndicator", "ProFeatureIndicatorRow", "HHDivider"],
            height: 740,
        ) {
            VStack(spacing: HHSpacing.space6) {
                HHAlert(title: "Information", message: "Supporting information stays visible on this page.")
                HHAlert(title: "Action unavailable", message: "Try again when you are ready.", variant: .destructive)
                HHAlert(title: "Dismissible information", message: "This example includes a close action.", dismissAccessibilityLabel: "Dismiss", onDismiss: {})
                HHOfflineBanner(title: "You are offline", message: "Changes will sync when you reconnect.")
                HHDivider()
                ProFeatureIndicator(accessibilityLabel: "Pro feature")
                ProFeatureIndicatorRow(accessibilityLabel: "Pro feature") { Text(verbatim: "Advanced options") }
            }
            .padding(HHSpacing.space4)
        }
    )
    samples.append(
        PreviewSample(
            "settings",
            "Settings rows and grouped surfaces",
            components: [
                "SettingsRow", "SettingsRowLeadingIcon", "SettingsRowTitleStack", "SettingsRowDisclosure", "SettingsChevron", "SettingsRowCheckmark", "SettingsRowValueText",
                "SettingsRowValueLabel", "SettingsConnectionStatusText", "SettingsSectionHeader", "SettingsSectionFooter", "SettingsInteractiveRow", "SettingsRowSessionMergeIcon",
                "SettingsLabelRow", "SettingsRowLabelStyle", "SettingsRowAssetIcon",
            ],
            height: 900,
            fitsContent: false,
        ) {
            List {
                Section {
                    SettingsInteractiveRow(.microphone) { SettingsRow(icon: "mic", title: "Microphone", valueText: "Built-in") }
                    SettingsRow(icon: "settings", title: "Options", subtitle: "Supporting description") { SettingsRowCheckmark(isSelected: true) }
                    SettingsRow(title: "Asset icon", leading: { SettingsRowAssetIcon(name: "HeidiIconSmall") })
                    SettingsRow(sessionMergeTitle: "Session groups")
                    SettingsRow(title: "Read-only value", showsChevron: false)
                    SettingsRow(icon: "bluetooth", title: "Connection") {
                        SettingsConnectionStatusText(isConnected: true, connectedTitle: "Connected", disconnectedTitle: "Disconnected")
                    }
                    SettingsRow(icon: "bluetooth", title: "Connection") {
                        SettingsConnectionStatusText(isConnected: false, connectedTitle: "Connected", disconnectedTitle: "Disconnected")
                    }
                    SettingsRow(icon: "info", title: "Learn more", prominence: .accent)
                } header: {
                    SettingsSectionHeader(title: "Preferences")
                } footer: {
                    SettingsSectionFooter(text: "The page uses surfaceSecondary; groups use surfaceTertiary.")
                }
                .settingsListGroupBackground()
                Section {
                    SettingsRow(titleText: "Selected option", subtitleText: "Supporting text", isSelected: true)
                    SettingsRow(icon: "info", title: "Localized value") { SettingsRowValueLabel(title: "Automatic") }
                    SettingsRow(icon: "info", title: "Verbatim value") { SettingsRowValueText(text: "ABC-123") }
                    SettingsLabelRow("Legacy label row", systemImage: "gear")
                } header: {
                    SettingsSectionHeader(title: "Increased prominence", prominence: .increased)
                }
                .settingsListGroupBackground()
            }
            .settingsListScreenStyle()
        }
    )
    samples.append(
        PreviewSample("tabs-header", "Bottom-sheet header and tab strip", components: ["HHBottomSheetHeader", "HHHorizontalTabStrip"], height: 430, fitsContent: false) {
            VStack(spacing: HHSpacing.space6) {
                HHBottomSheetHeader(
                    title: "Session details",
                    leadingIcon: "xmark",
                    leadingAccessibilityLabel: Text(verbatim: "Close"),
                    onLeadingTap: {},
                    trailingIcon: "ellipsis",
                    trailingAccessibilityLabel: Text(verbatim: "More"),
                    onTrailingTap: {},
                )
                HHHorizontalTabStrip(
                    items: [.init(id: "note", title: "Note"), .init(id: "transcript", title: "Transcript", badgeCount: 2)],
                    selectedItemID: "note",
                    addAccessibilityLabel: Text(verbatim: "Add"),
                    onAddTapped: {},
                    onItemSelected: { _ in },
                )
                HHHorizontalTabStrip(
                    items: [.init(id: "note", title: "Note"), .init(id: "transcript", title: "Transcript", badgeCount: 2)],
                    selectedItemID: "transcript",
                    isSelectionEnabled: false,
                    onItemSelected: { _ in },
                )
            }
            .background(HHColors.surfaceSecondary.color)
        }
    )
    for loading in [false, true] {
        samples.append(
            PreviewSample(
                "confirmation\(loading ? "-loading" : "")",
                "Confirmation dialog\(loading ? " · loading" : "")",
                components: ["HHConfirmationDialogView"],
                height: 550,
                fitsContent: false,
            ) {
                HHConfirmationDialogView(
                    title: "Confirm this action?",
                    message: "Review your choice before continuing.",
                    confirmTitle: "Confirm",
                    cancelTitle: "Cancel",
                    closeAccessibilityLabel: "Close",
                    onConfirm: {},
                    onCancel: {},
                    isLoading: loading,
                    loadingConfirmTitle: "Working…",
                )
            }
        )
    }
    samples.append(
        PreviewSample("prompt", "Ask Heidi and text entry", components: ["AskHeidiPromptBar", "AskHeidiAccessoryButton", "GrowingTextEditor", "SelectableTextView"], height: 520) {
            VStack(alignment: .leading, spacing: HHSpacing.space6) {
                AskHeidiPromptBar(placeholder: "Ask Heidi", onTap: {})
                HStack(spacing: HHSpacing.space4) {
                    AskHeidiAccessoryButton(icon: "plus", action: {})
                    AskHeidiAccessoryButton(icon: "mic", action: {})
                }
                GrowingTextEditor(
                    text: .constant(""),
                    measuredTextHeight: .constant(44),
                    minHeight: HHSizing.minTapTarget,
                    maxHeight: 120,
                    placeholder: "Write a message",
                    placeholderColor: HHColors.foregroundSecondary.color,
                )
                .frame(height: 80)
                SelectableTextView(text: "This selectable text is rendered by the native UIKit adapter using the p2 typography contract.")
            }
            .padding(HHSpacing.space4)
        }
    )
    samples.append(
        PreviewSample("number-pad", "Number buttons and phone keypad", components: ["HHNumberButton", "PhoneDialPad"], height: 650) {
            VStack(spacing: HHSpacing.space6) {
                HStack(spacing: HHSpacing.space4) {
                    HHNumberButton(value: "1", bodyText: "Default") {}
                    HHNumberButton(value: "2", bodyText: "Selected", isSelected: true) {}
                    HHNumberButton(value: "3", bodyText: "Unavailable", isSelectable: false) {}
                }
                PhoneDialPad(
                    onCharacterEntered: { _ in },
                    labelProvider: { key in LocalizedStringResource(stringLiteral: String(key.primaryCharacter)) },
                    holdHint: "Hold for plus",
                    plusActionLabel: "Plus",
                )
            }
            .padding(HHSpacing.space4)
        }
    )
    samples.append(
        PreviewSample("branding-promo", "Branding and promotional sheet", components: ["HeidiSignInLogoView", "HHPromoSheet"], height: 720, fitsContent: false) {
            VStack(spacing: HHSpacing.space6) {
                HeidiSignInLogoView(brandName: "Heidi")
                HHPromoSheet(
                    title: "Make room for care",
                    message: "A synthetic example of the shared promotional sheet.",
                    primaryTitle: "Continue",
                    onPrimaryTap: {},
                    secondaryTitle: "Maybe later",
                    onSecondaryTap: {},
                ) {
                    Image(systemName: "sparkles").font(HHFont.symbol(size: HHSizing.iconXLarge)).foregroundStyle(HHColors.foregroundBrand.color)
                }
            }
            .padding(HHSpacing.space4)
        }
    )
    for back in [false, true] {
        samples.append(
            PreviewSample(
                "sheet-toolbar\(back ? "-back" : "")",
                "Sheet toolbar\(back ? " · back" : " · close and commit")",
                components: ["SheetToolbar", "SheetToolbarCommitAction", "HHGlassButton"],
                height: 460,
                fitsContent: false,
            ) {
                NavigationStack {
                    VStack(spacing: HHSpacing.space6) {
                        Text(verbatim: "Native toolbar and footer chrome").hhTextStyle(.h4)
                        HHGlassButton(action: {}) { Text(verbatim: "Standard") }
                        HHGlassButton(prominence: .increased, action: {}) { Text(verbatim: "Prominent") }
                        HHGlassButton(isLoading: true, action: {}) { Text(verbatim: "Loading") }
                        HHGlassButton(action: {}) { Text(verbatim: "Disabled") }.disabled(true)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .sheetSurfaceStyle()
                    .toolbar {
                        SheetToolbar(title: "Sheet title", navigationStyle: back ? .back : .close, navigationAccessibilityLabel: back ? "Back" : "Close", onNavigationAction: {}) {
                            SheetToolbarCommitAction("Save", action: {})
                        }
                    }
                }
            }
        )
    }
    samples.append(
        PreviewSample("country-picker", "Country dial-code picker", components: ["CountryDialCodePickerView"], height: 580, fitsContent: false) {
            NavigationStack {
                CountryDialCodePickerView(
                    selectedRegion: .constant("AU"),
                    title: "Country",
                    searchPrompt: "Search countries",
                    loadRegions: { locale in
                        ["AU", "GB", "US"]
                            .map { region in
                                CountryRegionItem(
                                    region: region,
                                    name: locale.localizedString(forRegionCode: region) ?? region,
                                    dialCode: region == "AU" ? "61" : region == "GB" ? "44" : "1",
                                )
                            }
                    },
                )
            }
        }
    )
    return samples
}
