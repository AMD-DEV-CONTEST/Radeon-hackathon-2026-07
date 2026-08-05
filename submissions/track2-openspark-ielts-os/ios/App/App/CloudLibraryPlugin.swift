import Capacitor
import AVFoundation
import QuickLook
import Speech
import UniformTypeIdentifiers
import UIKit

@objc(CloudLibraryPlugin)
public class CloudLibraryPlugin: CAPPlugin, CAPBridgedPlugin, UIDocumentPickerDelegate, QLPreviewControllerDataSource, QLPreviewControllerDelegate {
    public let identifier = "CloudLibraryPlugin"
    public let jsName = "CloudLibrary"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "selectFolder", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openFile", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "speak", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopSpeak", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startTranscribe", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopTranscribe", returnType: CAPPluginReturnPromise)
    ]

    private let bookmarkKey = "ielts-os.cloud-library-bookmark"
    private let folderNameKey = "ielts-os.cloud-library-folder-name"
    private var folderCall: CAPPluginCall?
    private var previewURL: URL?
    private var accessedRoot: URL?
    // Keep the document-provider URL for the current launch as well as its bookmark.
    // This makes the first open reliable even while iCloud finishes persisting the bookmark.
    private var selectedRoot: URL?
    private let speech = AVSpeechSynthesizer()
    private var speakCompletion: (() -> Void)?
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    private var lastTranscript = ""

    @objc func speak(_ call: CAPPluginCall) {
        guard let text = call.getString("text"), !text.isEmpty else { return call.reject("缺少发音内容") }
        let wait = call.getBool("wait") ?? false
        DispatchQueue.main.async {
            self.speech.stopSpeaking(at: .immediate)
            let utterance = AVSpeechUtterance(string: text)
            utterance.voice = AVSpeechSynthesisVoice(language: call.getString("language") == "en-GB" ? "en-GB" : "en-US")
            utterance.rate = 0.43
            if wait {
                self.speech.delegate = self
                self.speakCompletion = { call.resolve() }
            }
            self.speech.speak(utterance)
            if !wait { call.resolve() }
        }
    }

    @objc func stopSpeak(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.speech.stopSpeaking(at: .immediate)
            call.resolve()
        }
    }

    @objc func startTranscribe(_ call: CAPPluginCall) {
        SFSpeechRecognizer.requestAuthorization { status in
            guard status == .authorized else {
                DispatchQueue.main.async { call.reject("语音识别权限未开启，请在系统设置中允许。") }
                return
            }
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                guard granted else {
                    DispatchQueue.main.async { call.reject("麦克风权限未开启，请在系统设置中允许。") }
                    return
                }
                DispatchQueue.main.async {
                    do {
                        try self.beginTranscribe()
                        call.resolve()
                    } catch {
                        call.reject("无法启动语音识别：\(error.localizedDescription)")
                    }
                }
            }
        }
    }

    private func beginTranscribe() throws {
        stopTranscribeEngine()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        recognitionRequest = request
        lastTranscript = ""
        let inputNode = audioEngine.inputNode
        recognitionTask = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let result {
                self.lastTranscript = result.bestTranscription.formattedString
                self.notifyListeners("transcript", data: ["text": self.lastTranscript, "final": result.isFinal])
            }
            if error != nil || (result?.isFinal ?? false) {
                self.stopTranscribeEngine()
            }
        }
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }
        audioEngine.prepare()
        try audioEngine.start()
    }

    @objc func stopTranscribe(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.stopTranscribeEngine()
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            call.resolve(["text": self.lastTranscript])
        }
    }

    private func stopTranscribeEngine() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
    }

    @objc func selectFolder(_ call: CAPPluginCall) {
        folderCall = call
        DispatchQueue.main.async {
            let alert = UIAlertController(
                title: "首次打开需授权资料目录",
                message: "下一页请停留在“雅思全套资料”，点击右上角“打开”。授权完成后，App 会自动打开刚才选择的文件。",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "取消", style: .cancel) { _ in
                self.folderCall?.reject("已取消选择资料目录", "cancelled")
                self.folderCall = nil
            })
            alert.addAction(UIAlertAction(title: "继续选择", style: .default) { _ in
                self.presentFolderPicker()
            })
            self.bridge?.viewController?.present(alert, animated: true)
        }
    }

    private func presentFolderPicker() {
        DispatchQueue.main.async {
            let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
            picker.delegate = self
            picker.allowsMultipleSelection = false
            self.bridge?.viewController?.present(picker, animated: true)
        }
    }

    public func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let url = urls.first else { return folderCall?.reject("未选择资料目录") ?? () }
        // The URL supplied by UIDocumentPicker is valid for this app session even
        // when a third-party/iCloud file provider refuses a persistent bookmark.
        selectedRoot = url
        let didStartAccess = url.startAccessingSecurityScopedResource()
        defer {
            if didStartAccess { url.stopAccessingSecurityScopedResource() }
        }
        do {
            // iOS embeds an implicit security scope by default. The explicit
            // withSecurityScope option is macOS/Catalyst-only.
            let bookmark = try url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
            UserDefaults.standard.set(bookmark, forKey: bookmarkKey)
            UserDefaults.standard.set(url.lastPathComponent, forKey: folderNameKey)
            UserDefaults.standard.synchronize()
            folderCall?.resolve(["name": url.lastPathComponent, "saved": true])
        } catch {
            // Do not block the learning flow: the selected directory remains usable
            // for the running app. A later iOS-compatible storage strategy can
            // restore it after relaunch.
            folderCall?.resolve(["name": url.lastPathComponent, "saved": false])
        }
        folderCall = nil
    }

    public func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        folderCall?.reject("已取消选择资料目录", "cancelled")
        folderCall = nil
    }

    @objc func openFile(_ call: CAPPluginCall) {
        guard let relativePath = call.getString("relativePath"), !relativePath.isEmpty, !relativePath.split(separator: "/").contains("..") else {
            return call.reject("无效的资料路径")
        }
        do {
            let root: URL
            if let selectedRoot {
                root = selectedRoot
            } else {
                guard let bookmark = UserDefaults.standard.data(forKey: bookmarkKey) else {
                    return call.reject("请先选择 iCloud 资料目录", "folder_not_selected")
                }
                var stale = false
                root = try URL(resolvingBookmarkData: bookmark, options: [.withoutImplicitStartAccessing], relativeTo: nil, bookmarkDataIsStale: &stale)
                if stale {
                    let refreshed = try root.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil)
                    UserDefaults.standard.set(refreshed, forKey: bookmarkKey)
                    UserDefaults.standard.synchronize()
                }
            }
            guard root.startAccessingSecurityScopedResource() else {
                return call.reject("iCloud 资料目录授权已失效，请重新选择", "folder_not_selected")
            }
            let file = relativePath.split(separator: "/").reduce(root) { $0.appendingPathComponent(String($1)) }
            guard FileManager.default.fileExists(atPath: file.path) else {
                root.stopAccessingSecurityScopedResource()
                return call.reject("资料文件不存在，请刷新资料目录")
            }
            if (try? file.resourceValues(forKeys: [.isUbiquitousItemKey]).isUbiquitousItem) == true {
                try? FileManager.default.startDownloadingUbiquitousItem(at: file)
            }
            previewURL = file
            accessedRoot = root
            DispatchQueue.main.async {
                let preview = QLPreviewController()
                preview.dataSource = self
                preview.delegate = self
                self.bridge?.viewController?.present(preview, animated: true)
                call.resolve(["opened": true])
            }
        } catch {
            call.reject("无法打开 iCloud 资料", nil, error)
        }
    }

    public func numberOfPreviewItems(in controller: QLPreviewController) -> Int { previewURL == nil ? 0 : 1 }
    public func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem { previewURL! as NSURL }
    public func previewControllerDidDismiss(_ controller: QLPreviewController) {
        accessedRoot?.stopAccessingSecurityScopedResource()
        accessedRoot = nil
        previewURL = nil
    }
}

@objc(IELTSBridgeViewController)
public class IELTSBridgeViewController: CAPBridgeViewController {
    public override func capacitorDidLoad() {
        bridge?.registerPluginInstance(CloudLibraryPlugin())
    }
}

extension CloudLibraryPlugin: AVSpeechSynthesizerDelegate {
    public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let done = speakCompletion
        speakCompletion = nil
        done?()
    }

    public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        let done = speakCompletion
        speakCompletion = nil
        done?()
    }
}
