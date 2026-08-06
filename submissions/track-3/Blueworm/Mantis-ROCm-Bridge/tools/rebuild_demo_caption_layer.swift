#!/usr/bin/env swift
import AVFoundation
import CoreMedia
import QuartzCore
import AppKit
import Dispatch
import Foundation

private struct SubtitleSegment {
    let start: Double
    let end: Double
    let text: String
}

private let expectedInputSHA256 = "62ab601f33579290a93d3ab5d97fe88a1345522d0182b53aa244c236b52aa411"
private let expectedWidth = 640
private let expectedHeight = 480
private let expectedDuration = 162.0
private let maskHeight = 80.0

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

private enum RebuildError: Error, CustomStringConvertible {
    case usage
    case outputExists(String)
    case invalidInput(String)
    case exportFailed(String)

    var description: String {
        switch self {
        case .usage:
            return "usage: rebuild_demo_caption_layer <v1-input.mp4> <fresh-v2-output.mp4>"
        case .outputExists(let path):
            return "refusing to overwrite existing output: \(path)"
        case .invalidInput(let reason):
            return "invalid input: \(reason)"
        case .exportFailed(let reason):
            return "export failed: \(reason)"
        }
    }
}

private func sha256(_ url: URL) throws -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/shasum")
    process.arguments = ["-a", "256", url.path]
    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = pipe
    try process.run()
    process.waitUntilExit()
    let output = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    guard process.terminationStatus == 0, let digest = output.split(separator: " ").first else {
        throw RebuildError.invalidInput("could not compute SHA-256: \(output.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
    return String(digest)
}

private func opacityAnimation(for segment: SubtitleSegment) -> CAKeyframeAnimation {
    let animation = CAKeyframeAnimation(keyPath: "opacity")
    if segment.start == 0 {
        animation.values = [1, 0]
        animation.keyTimes = [0, NSNumber(value: segment.end / expectedDuration)]
    } else if segment.end == expectedDuration {
        animation.values = [0, 1]
        animation.keyTimes = [0, NSNumber(value: segment.start / expectedDuration)]
    } else {
        animation.values = [0, 1, 0]
        animation.keyTimes = [
            0,
            NSNumber(value: segment.start / expectedDuration),
            NSNumber(value: segment.end / expectedDuration),
        ]
    }
    animation.calculationMode = .discrete
    animation.duration = expectedDuration
    animation.beginTime = AVCoreAnimationBeginTimeAtZero
    animation.isRemovedOnCompletion = false
    animation.fillMode = .both
    return animation
}

private func makeOverlay(size: CGSize) -> (CALayer, CALayer) {
    let parent = CALayer()
    parent.frame = CGRect(origin: .zero, size: size)

    let video = CALayer()
    video.frame = parent.bounds
    parent.addSublayer(video)

    let mask = CALayer()
    mask.frame = CGRect(x: 0, y: 0, width: size.width, height: maskHeight)
    mask.backgroundColor = NSColor(calibratedRed: 12.0 / 255.0, green: 14.0 / 255.0, blue: 22.0 / 255.0, alpha: 1).cgColor
    parent.addSublayer(mask)

    for segment in subtitleSegments {
        let text = CATextLayer()
        text.frame = CGRect(x: 28, y: 8, width: size.width - 56, height: maskHeight - 16)
        text.string = segment.text
        text.font = NSFont.systemFont(ofSize: 19, weight: .medium)
        text.fontSize = 19
        text.foregroundColor = NSColor.white.cgColor
        text.alignmentMode = .center
        text.isWrapped = true
        text.contentsScale = 2
        text.opacity = 0
        text.add(opacityAnimation(for: segment), forKey: "captionVisibility")
        parent.addSublayer(text)
    }
    return (parent, video)
}

private func rebuild(input: URL, output: URL) async throws {
    let fileManager = FileManager.default
    guard fileManager.fileExists(atPath: input.path) else {
        throw RebuildError.invalidInput("missing file: \(input.path)")
    }
    guard !fileManager.fileExists(atPath: output.path) else {
        throw RebuildError.outputExists(output.path)
    }
    guard try sha256(input) == expectedInputSHA256 else {
        throw RebuildError.invalidInput("SHA-256 does not match the frozen v1")
    }

    let asset = AVURLAsset(url: input)
    let duration = try await asset.load(.duration)
    let sourceTracks = try await asset.loadTracks(withMediaType: .video)
    guard let sourceTrack = sourceTracks.first else {
        throw RebuildError.invalidInput("no video track")
    }
    let naturalSize = try await sourceTrack.load(.naturalSize)
    let preferredTransform = try await sourceTrack.load(.preferredTransform)
    let transformedRect = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform)
    let displaySize = CGSize(width: abs(transformedRect.width), height: abs(transformedRect.height))
    guard Int(displaySize.width.rounded()) == expectedWidth,
          Int(displaySize.height.rounded()) == expectedHeight else {
        throw RebuildError.invalidInput("expected 640x480 display geometry, got \(displaySize)")
    }
    guard abs(CMTimeGetSeconds(duration) - expectedDuration) < 0.1 else {
        throw RebuildError.invalidInput("expected approximately 162 seconds, got \(CMTimeGetSeconds(duration))")
    }

    let composition = AVMutableComposition()
    guard let compositionTrack = composition.addMutableTrack(
        withMediaType: .video,
        preferredTrackID: kCMPersistentTrackID_Invalid
    ) else {
        throw RebuildError.invalidInput("could not create composition video track")
    }
    try compositionTrack.insertTimeRange(CMTimeRange(start: .zero, duration: duration), of: sourceTrack, at: .zero)

    let instruction = AVMutableVideoCompositionInstruction()
    instruction.timeRange = CMTimeRange(start: .zero, duration: duration)
    let layerInstruction = AVMutableVideoCompositionLayerInstruction(assetTrack: compositionTrack)
    layerInstruction.setTransform(preferredTransform, at: .zero)
    instruction.layerInstructions = [layerInstruction]

    let videoComposition = AVMutableVideoComposition()
    videoComposition.instructions = [instruction]
    videoComposition.renderSize = displaySize
    videoComposition.frameDuration = CMTime(value: 1, timescale: 30)
    let (parentLayer, videoLayer) = makeOverlay(size: displaySize)
    videoComposition.animationTool = AVVideoCompositionCoreAnimationTool(
        postProcessingAsVideoLayer: videoLayer,
        in: parentLayer
    )

    guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
        throw RebuildError.exportFailed("could not create AVAssetExportSession")
    }
    exporter.videoComposition = videoComposition
    exporter.shouldOptimizeForNetworkUse = true
    do {
        try await exporter.export(to: output, as: .mp4)
    } catch {
        throw RebuildError.exportFailed(error.localizedDescription)
    }
}

Task {
    do {
        guard CommandLine.arguments.count == 3 else { throw RebuildError.usage }
        let input = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
        let output = URL(fileURLWithPath: CommandLine.arguments[2]).standardizedFileURL
        try await rebuild(input: input, output: output)
        print("EXPORT_OK \(output.path)")
        Foundation.exit(0)
    } catch {
        FileHandle.standardError.write(Data("ERROR \(error)\n".utf8))
        Foundation.exit(1)
    }
}
dispatchMain()
