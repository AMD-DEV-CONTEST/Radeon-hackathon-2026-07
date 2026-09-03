#!/usr/bin/env swift
import AVFoundation
import CoreImage
import CoreMedia
import CoreText
import CryptoKit
import Dispatch
import Foundation
import ImageIO
import VideoToolbox

private struct SubtitleSegment {
    let start: Double
    let end: Double
    let text: String
}

private struct ProofSpec {
    let index: Int
    let seconds: Double
    let filename: String
}

private let expectedProtocolSHA256 = "8b65231b4e791102419c8ea62cdc2ffb074089035c68ce3967266dc94b010439"
private let expectedV1SHA256 = "62ab601f33579290a93d3ab5d97fe88a1345522d0182b53aa244c236b52aa411"
private let expectedV2SHA256 = "7d68a35b4cd4bfd03645a2d03cd382a31ba3023bb78324115fea24295f68abfb"
private let expectedV2ReceiptSHA256 = "1c687ca5ddfdf5b8b8b8e4c5143cf50a37a1c64a2d49ee90298eed78b2e27cbd"
private let protocolPath = ".ops/wip/submission-sprint-20260805-v1/WP-VIDEO-FRAMEWRITER-V3-PROOF-20260805-v1.json"
private let v2Path = "submission/media/Mantis_ROCM_Bridge_demo_20260805_v2.mp4"
private let v2ReceiptPath = ".ops/wip/submission-sprint-20260805-v1/video-caption-v2-build-20260805-v1/build_receipt.json"
private let sourcePath = "tools/rebuild_demo_caption_layer_v3.swift"
private let testPath = "tests/test_demo_caption_layer_v3.py"
private let reservedV3Filename = "Mantis_ROCM_Bridge_demo_20260805_v3.mp4"
private let reservedV3Path = "submission/media/\(reservedV3Filename)"
private let expectedWidth = 640
private let expectedHeight = 480
private let expectedDuration = 162.0
private let maskHeight = 80

private let subtitleSegments = [
    SubtitleSegment(start: 0, end: 9, text: "Mantis-ROCm Bridge: a robot adaptation and task-porting framework for AMD Radeon and ROCm."),
    SubtitleSegment(start: 9, end: 23, text: "Hidden interface assumptions break robot ports. We turn them into versioned contracts."),
    SubtitleSegment(start: 23, end: 38, text: "Profile, URDF-to-ROCm compiler, ROCm-native port, ACT training, staged evaluation."),
    SubtitleSegment(start: 38, end: 52, text: "One AMD Radeon GPU, ROCm 7.2.1, PyTorch 2.9.1, Genesis on the gs.amdgpu backend."),
    SubtitleSegment(start: 52, end: 64, text: "The Mantis dual-arm robot in Genesis simulation, rendered on the AMD Radeon GPU (gs.amdgpu)."),
    SubtitleSegment(start: 64, end: 71, text: "Rigid-body physics simulation running on the AMD Radeon GPU via Genesis gs.amdgpu."),
    SubtitleSegment(start: 71, end: 89, text: "ACT policy trained on Mantis dual-arm data on AMD. Loss is descriptive, not task success."),
    SubtitleSegment(start: 89, end: 104, text: "Open-loop inference on AMD: twelve finite actions from the trained policy."),
    SubtitleSegment(start: 104, end: 119, text: "The URDF-to-ROCm compiler emits an executable bundle verified on AMD, with bf16 tuning."),
    SubtitleSegment(start: 119, end: 137, text: "The official AMD closed-loop result is zero of ten - an honest, published negative."),
    SubtitleSegment(start: 137, end: 152, text: "The contribution is an auditable porting framework and honest promotion discipline."),
    SubtitleSegment(start: 152, end: 162, text: "Mantis-ROCm Bridge - a robot adaptation framework on AMD Radeon and ROCm."),
]

private let proofSpecs = [
    ProofSpec(index: 1, seconds: 1, filename: "proof_01_000001000ms.png"),
    ProofSpec(index: 2, seconds: 10, filename: "proof_02_000010000ms.png"),
    ProofSpec(index: 3, seconds: 24, filename: "proof_03_000024000ms.png"),
    ProofSpec(index: 4, seconds: 39, filename: "proof_04_000039000ms.png"),
    ProofSpec(index: 5, seconds: 53, filename: "proof_05_000053000ms.png"),
    ProofSpec(index: 6, seconds: 65, filename: "proof_06_000065000ms.png"),
    ProofSpec(index: 7, seconds: 72, filename: "proof_07_000072000ms.png"),
    ProofSpec(index: 8, seconds: 90, filename: "proof_08_000090000ms.png"),
    ProofSpec(index: 9, seconds: 105, filename: "proof_09_000105000ms.png"),
    ProofSpec(index: 10, seconds: 120, filename: "proof_10_000120000ms.png"),
    ProofSpec(index: 11, seconds: 138, filename: "proof_11_000138000ms.png"),
    ProofSpec(index: 12, seconds: 153, filename: "proof_12_000153000ms.png"),
]

private enum ToolError: Error, CustomStringConvertible {
    case usage
    case invalidInput(String)
    case outputExists(String)
    case proofGate(String)
    case reader(String)
    case renderer(String)
    case writer(String)

    var description: String {
        switch self {
        case .usage:
            return "usage: rebuild_demo_caption_layer_v3 proof <v1-input.mp4> <fresh-proof-root> | export <v1-input.mp4> <fresh-v3-output.mp4> <proof-go-receipt.json>"
        case .invalidInput(let reason): return "invalid input: \(reason)"
        case .outputExists(let path): return "refusing to overwrite existing output: \(path)"
        case .proofGate(let reason): return "proof gate rejected: \(reason)"
        case .reader(let reason): return "reader failed: \(reason)"
        case .renderer(let reason): return "renderer failed: \(reason)"
        case .writer(let reason): return "writer failed: \(reason)"
        }
    }
}

private func sha256(_ url: URL) throws -> String {
    let data = try Data(contentsOf: url, options: .mappedIfSafe)
    return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

private func projectURL(_ relativePath: String) -> URL {
    URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
        .appendingPathComponent(relativePath)
        .standardizedFileURL
}

private func relativeProjectPath(_ url: URL) throws -> String {
    let root = projectURL("").path + "/"
    let path = url.standardizedFileURL.path
    guard path.hasPrefix(root) else {
        throw ToolError.invalidInput("artifact is outside the project root: \(path)")
    }
    return String(path.dropFirst(root.count))
}

private func subtitleIndex(at seconds: Double) -> Int? {
    subtitleSegments.firstIndex { seconds >= $0.start && seconds < $0.end }
}

private func makePixelBuffer() throws -> CVPixelBuffer {
    let attributes: [CFString: Any] = [
        kCVPixelBufferCGImageCompatibilityKey: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey: true,
        kCVPixelBufferIOSurfacePropertiesKey: [:] as CFDictionary,
    ]
    var pixelBuffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        expectedWidth,
        expectedHeight,
        kCVPixelFormatType_32BGRA,
        attributes as CFDictionary,
        &pixelBuffer
    )
    guard status == kCVReturnSuccess, let pixelBuffer else {
        throw ToolError.renderer("could not allocate BGRA pixel buffer: \(status)")
    }
    return pixelBuffer
}

private func renderFrame(
    source: CVPixelBuffer,
    destination: CVPixelBuffer,
    presentationTime: CMTime,
    ciContext: CIContext
) throws -> Int {
    guard CVPixelBufferGetWidth(source) == expectedWidth,
          CVPixelBufferGetHeight(source) == expectedHeight,
          CVPixelBufferGetWidth(destination) == expectedWidth,
          CVPixelBufferGetHeight(destination) == expectedHeight else {
        throw ToolError.renderer("expected 640x480 source and destination buffers")
    }
    let seconds = CMTimeGetSeconds(presentationTime)
    guard seconds.isFinite, let index = subtitleIndex(at: seconds) else {
        throw ToolError.renderer("no frozen subtitle for presentation time \(seconds)")
    }

    let bounds = CGRect(x: 0, y: 0, width: expectedWidth, height: expectedHeight)
    ciContext.render(
        CIImage(cvPixelBuffer: source),
        to: destination,
        bounds: bounds,
        colorSpace: CGColorSpaceCreateDeviceRGB()
    )

    CVPixelBufferLockBaseAddress(destination, [])
    defer { CVPixelBufferUnlockBaseAddress(destination, []) }
    guard let baseAddress = CVPixelBufferGetBaseAddress(destination) else {
        throw ToolError.renderer("destination pixel buffer has no base address")
    }
    let bitmapInfo = CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue
    guard let context = CGContext(
        data: baseAddress,
        width: expectedWidth,
        height: expectedHeight,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(destination),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: bitmapInfo
    ) else {
        throw ToolError.renderer("could not create bitmap context")
    }

    context.setFillColor(red: 12.0 / 255.0, green: 14.0 / 255.0, blue: 22.0 / 255.0, alpha: 1)
    context.fill(CGRect(x: 0, y: 0, width: expectedWidth, height: maskHeight))

    var alignment = CTTextAlignment.center
    let paragraphStyle = withUnsafePointer(to: &alignment) { pointer -> CTParagraphStyle in
        var setting = CTParagraphStyleSetting(
            spec: .alignment,
            valueSize: MemoryLayout<CTTextAlignment>.size,
            value: pointer
        )
        return CTParagraphStyleCreate(&setting, 1)
    }
    let attributes: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(kCTFontAttributeName as String): CTFontCreateWithName("Helvetica Neue Medium" as CFString, 19, nil),
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(red: 1, green: 1, blue: 1, alpha: 1),
        NSAttributedString.Key(kCTParagraphStyleAttributeName as String): paragraphStyle,
    ]
    let attributed = NSAttributedString(string: subtitleSegments[index].text, attributes: attributes)
    let framesetter = CTFramesetterCreateWithAttributedString(attributed as CFAttributedString)
    let textPath = CGPath(rect: CGRect(x: 28, y: 8, width: expectedWidth - 56, height: maskHeight - 16), transform: nil)
    let textFrame = CTFramesetterCreateFrame(framesetter, CFRange(), textPath, nil)
    context.textMatrix = .identity
    CTFrameDraw(textFrame, context)
    return index
}

private func pngData(from pixelBuffer: CVPixelBuffer) throws -> Data {
    var image: CGImage?
    let status = VTCreateCGImageFromCVPixelBuffer(pixelBuffer, options: nil, imageOut: &image)
    guard status == noErr, let image else {
        throw ToolError.renderer("could not create proof CGImage: \(status)")
    }
    let data = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(data, "public.png" as CFString, 1, nil) else {
        throw ToolError.renderer("could not create PNG destination")
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw ToolError.renderer("could not finalize PNG")
    }
    return data as Data
}

private func validateEntryCriteria(input: URL) throws {
    let checks = [
        (input, expectedV1SHA256, "frozen v1"),
        (projectURL(protocolPath), expectedProtocolSHA256, "frozen v3 proof protocol"),
        (projectURL(v2Path), expectedV2SHA256, "immutable v2 negative evidence"),
        (projectURL(v2ReceiptPath), expectedV2ReceiptSHA256, "immutable v2 receipt"),
    ]
    for (url, expected, label) in checks {
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw ToolError.invalidInput("missing \(label): \(url.path)")
        }
        guard try sha256(url) == expected else {
            throw ToolError.invalidInput("SHA-256 mismatch for \(label)")
        }
    }
    guard !FileManager.default.fileExists(atPath: projectURL(reservedV3Path).path) else {
        throw ToolError.outputExists(reservedV3Path)
    }
}

private func validatedVideoTrack(input: URL) async throws -> (AVURLAsset, AVAssetTrack) {
    try validateEntryCriteria(input: input)
    let asset = AVURLAsset(url: input)
    let duration = try await asset.load(.duration)
    guard abs(CMTimeGetSeconds(duration) - expectedDuration) < 0.1 else {
        throw ToolError.invalidInput("expected approximately 162 seconds")
    }
    guard let track = try await asset.loadTracks(withMediaType: .video).first else {
        throw ToolError.invalidInput("no video track")
    }
    let size = try await track.load(.naturalSize)
    let transform = try await track.load(.preferredTransform)
    guard Int(size.width.rounded()) == expectedWidth, Int(size.height.rounded()) == expectedHeight else {
        throw ToolError.invalidInput("expected 640x480 natural geometry")
    }
    guard transform == .identity else {
        throw ToolError.invalidInput("frozen input must have identity preferred transform")
    }
    return (asset, track)
}

private func reader(asset: AVAsset, track: AVAssetTrack) throws -> (AVAssetReader, AVAssetReaderTrackOutput) {
    let reader = try AVAssetReader(asset: asset)
    let output = AVAssetReaderTrackOutput(
        track: track,
        outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
    )
    output.alwaysCopiesSampleData = false
    guard reader.canAdd(output) else { throw ToolError.reader("cannot add BGRA track output") }
    reader.add(output)
    guard reader.startReading() else {
        throw ToolError.reader(reader.error?.localizedDescription ?? "startReading returned false")
    }
    return (reader, output)
}

private func writeJSON(_ object: Any, to url: URL) throws {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    var terminated = data
    terminated.append(0x0A)
    try terminated.write(to: url, options: .withoutOverwriting)
}

private func runProof(input: URL, proofRoot: URL) async throws {
    let fileManager = FileManager.default
    let rootValues = try proofRoot.resourceValues(forKeys: [.isDirectoryKey])
    guard rootValues.isDirectory == true else {
        throw ToolError.invalidInput("proof root must already exist as the compile output directory")
    }
    let initialNames = try Set(fileManager.contentsOfDirectory(atPath: proofRoot.path))
    guard initialNames == Set(["rebuild_demo_caption_layer_v3"]) else {
        throw ToolError.outputExists("proof root is not fresh: \(proofRoot.path)")
    }

    let (asset, track) = try await validatedVideoTrack(input: input)
    let (assetReader, output) = try reader(asset: asset, track: track)
    let ciContext = CIContext(options: [.cacheIntermediates: false])
    var targetIndex = 0
    var proofs: [[String: Any]] = []

    while targetIndex < proofSpecs.count, let sample = output.copyNextSampleBuffer() {
        autoreleasepool {
            let spec = proofSpecs[targetIndex]
            let presentationTime = CMSampleBufferGetPresentationTimeStamp(sample)
            let actualSeconds = CMTimeGetSeconds(presentationTime)
            guard actualSeconds + 0.0005 >= spec.seconds else { return }
            do {
                guard let source = CMSampleBufferGetImageBuffer(sample) else {
                    throw ToolError.reader("sample has no pixel buffer")
                }
                let destination = try makePixelBuffer()
                let subtitleIndex = try renderFrame(
                    source: source,
                    destination: destination,
                    presentationTime: presentationTime,
                    ciContext: ciContext
                )
                let outputURL = proofRoot.appendingPathComponent(spec.filename)
                try pngData(from: destination).write(to: outputURL, options: .withoutOverwriting)
                proofs.append([
                    "actual_seconds": actualSeconds,
                    "filename": spec.filename,
                    "height": expectedHeight,
                    "index": spec.index,
                    "requested_seconds": spec.seconds,
                    "sha256": try sha256(outputURL),
                    "subtitle_index": subtitleIndex + 1,
                    "subtitle_text": subtitleSegments[subtitleIndex].text,
                    "width": expectedWidth,
                ])
                targetIndex += 1
            } catch {
                proofs.append(["error": String(describing: error), "index": spec.index])
            }
        }
        if proofs.last?["error"] != nil {
            throw ToolError.renderer(proofs.last?["error"] as? String ?? "unknown proof error")
        }
    }
    if assetReader.status == .reading { assetReader.cancelReading() }
    guard targetIndex == proofSpecs.count else {
        throw ToolError.reader("decoded only \(targetIndex) of \(proofSpecs.count) proof timestamps")
    }

    let executableURL = proofRoot.appendingPathComponent("rebuild_demo_caption_layer_v3")
    let receiptURL = proofRoot.appendingPathComponent("proof_receipt.json")
    let manifestURL = proofRoot.appendingPathComponent("SHA256SUMS")
    let sourceURL = projectURL(sourcePath)
    let testURL = projectURL(testPath)
    let receipt: [String: Any] = [
        "schema_version": 1,
        "work_package_id": "WP-VIDEO-FRAMEWRITER-V3-PROOF-20260805-v1",
        "status": "proof_rendered_pending_independent_review",
        "decision": "NOT_REVIEWED",
        "created_at_utc": ISO8601DateFormatter().string(from: Date()),
        "protocol_sha256": expectedProtocolSHA256,
        "input_path": try relativeProjectPath(input),
        "input_sha256": expectedV1SHA256,
        "immutable_v2_sha256": expectedV2SHA256,
        "renderer_source_path": sourcePath,
        "renderer_source_sha256": try sha256(sourceURL),
        "renderer_executable_sha256": try sha256(executableURL),
        "renderer": "AVAssetReader plus timestamp-selected shared pixel-buffer renderFrame; no Core Animation timing",
        "proofs": proofs,
        "proof_count": proofs.count,
        "reserved_v3_mp4": reservedV3Path,
        "reserved_v3_mp4_absent": !fileManager.fileExists(atPath: projectURL(reservedV3Path).path),
        "unverified_claims": [
            "Independent original-resolution proof inspection has not run.",
            "PROOF_GO is not claimed.",
            "No v3 MP4 export, full decode, or VIDEO_GO is established.",
        ],
        "claim_boundary": "This receipt records proof rendering only; it does not establish PROOF_GO, a completed v3 video, VIDEO_GO, task success, release, PR, submission, or competition acceptance.",
    ]
    try writeJSON(receipt, to: receiptURL)

    var manifestURLs = [
        projectURL(protocolPath), input, projectURL(v2Path), projectURL(v2ReceiptPath),
        sourceURL, testURL, executableURL, receiptURL,
    ]
    manifestURLs.append(contentsOf: proofSpecs.map { proofRoot.appendingPathComponent($0.filename) })
    let manifestLines = try manifestURLs.map { url in
        "\(try sha256(url))  \(try relativeProjectPath(url))"
    }.sorted().joined(separator: "\n") + "\n"
    try Data(manifestLines.utf8).write(to: manifestURL, options: .withoutOverwriting)

    let finalNames = try Set(fileManager.contentsOfDirectory(atPath: proofRoot.path))
    let expectedNames = Set(["rebuild_demo_caption_layer_v3", "proof_receipt.json", "SHA256SUMS"] + proofSpecs.map(\.filename))
    guard finalNames == expectedNames else {
        throw ToolError.outputExists("proof root contains unexpected artifacts")
    }
    guard !fileManager.fileExists(atPath: projectURL(reservedV3Path).path) else {
        throw ToolError.outputExists(reservedV3Path)
    }
    print("PROOF_RENDERED_PENDING_REVIEW \(proofRoot.path)")
}

private func safeProjectArtifact(_ path: String) throws -> URL {
    guard !path.hasPrefix("/"), !path.split(separator: "/").contains("..") else {
        throw ToolError.proofGate("artifact path must be project-relative and confined")
    }
    return projectURL(path)
}

private func validateProofGate(_ gateURL: URL) throws {
    let object = try JSONSerialization.jsonObject(with: Data(contentsOf: gateURL))
    guard let gate = object as? [String: Any] else { throw ToolError.proofGate("receipt is not a JSON object") }
    guard gate["decision"] as? String == "PROOF_GO",
          gate["p0"] as? Int == 0,
          gate["p1"] as? Int == 0 else {
        throw ToolError.proofGate("requires decision=PROOF_GO, p0=0, and p1=0")
    }
    guard gate["protocol_sha256"] as? String == expectedProtocolSHA256,
          gate["input_sha256"] as? String == expectedV1SHA256 else {
        throw ToolError.proofGate("protocol or input identity mismatch")
    }
    guard gate["renderer_source_sha256"] as? String == (try sha256(projectURL(sourcePath))) else {
        throw ToolError.proofGate("renderer source identity mismatch")
    }
    for (pathKey, hashKey) in [("proof_receipt_path", "proof_receipt_sha256"), ("proof_manifest_path", "proof_manifest_sha256")] {
        guard let path = gate[pathKey] as? String, let expectedHash = gate[hashKey] as? String,
              expectedHash.count == 64 else {
            throw ToolError.proofGate("missing hash lock for \(pathKey)")
        }
        let artifact = try safeProjectArtifact(path)
        guard FileManager.default.fileExists(atPath: artifact.path), try sha256(artifact) == expectedHash else {
            throw ToolError.proofGate("hash lock mismatch for \(path)")
        }
    }
}

private func exportVideo(input: URL, output: URL, proofGate: URL) async throws {
    guard output.lastPathComponent == reservedV3Filename else {
        throw ToolError.invalidInput("export output must be \(reservedV3Filename)")
    }
    guard !FileManager.default.fileExists(atPath: output.path) else {
        throw ToolError.outputExists(output.path)
    }
    try validateProofGate(proofGate)
    let (asset, track) = try await validatedVideoTrack(input: input)
    let (assetReader, readerOutput) = try reader(asset: asset, track: track)
    let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
    let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: expectedWidth,
        AVVideoHeightKey: expectedHeight,
    ])
    writerInput.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
        assetWriterInput: writerInput,
        sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: expectedWidth,
            kCVPixelBufferHeightKey as String: expectedHeight,
        ]
    )
    guard writer.canAdd(writerInput) else { throw ToolError.writer("cannot add H.264 video input") }
    writer.add(writerInput)
    guard writer.startWriting() else { throw ToolError.writer(writer.error?.localizedDescription ?? "startWriting returned false") }
    writer.startSession(atSourceTime: .zero)
    let ciContext = CIContext(options: [.cacheIntermediates: false])

    while let sample = readerOutput.copyNextSampleBuffer() {
        while !writerInput.isReadyForMoreMediaData {
            if writer.status == .failed { throw ToolError.writer(writer.error?.localizedDescription ?? "writer failed") }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        guard let source = CMSampleBufferGetImageBuffer(sample) else { throw ToolError.reader("sample has no pixel buffer") }
        let presentationTime = CMSampleBufferGetPresentationTimeStamp(sample)
        let destination = try makePixelBuffer()
        _ = try renderFrame(source: source, destination: destination, presentationTime: presentationTime, ciContext: ciContext)
        guard adaptor.append(destination, withPresentationTime: presentationTime) else {
            throw ToolError.writer(writer.error?.localizedDescription ?? "pixel-buffer append returned false")
        }
    }
    guard assetReader.status == .completed else {
        throw ToolError.reader(assetReader.error?.localizedDescription ?? "reader did not complete")
    }
    writerInput.markAsFinished()
    await withCheckedContinuation { continuation in
        writer.finishWriting { continuation.resume() }
    }
    guard writer.status == .completed else {
        throw ToolError.writer(writer.error?.localizedDescription ?? "writer did not complete")
    }
    print("EXPORT_OK \(output.path)")
}

Task {
    do {
        guard CommandLine.arguments.count >= 2 else { throw ToolError.usage }
        switch CommandLine.arguments[1] {
        case "proof":
            guard CommandLine.arguments.count == 4 else { throw ToolError.usage }
            try await runProof(
                input: URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL,
                proofRoot: URL(fileURLWithPath: CommandLine.arguments[3], isDirectory: true).standardizedFileURL
            )
        case "export":
            guard CommandLine.arguments.count == 5 else { throw ToolError.usage }
            try await exportVideo(
                input: URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL,
                output: URL(fileURLWithPath: CommandLine.arguments[3]).standardizedFileURL,
                proofGate: URL(fileURLWithPath: CommandLine.arguments[4]).standardizedFileURL
            )
        default:
            throw ToolError.usage
        }
        Foundation.exit(0)
    } catch {
        FileHandle.standardError.write(Data("ERROR \(error)\n".utf8))
        Foundation.exit(1)
    }
}
dispatchMain()
