// On-device OCR for image-only annual-report covers; no network or credentials.
import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 2,
      let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Cannot read disclosure cover image\n", stderr)
    exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
do {
    try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
    for observation in request.results ?? [] {
        if let text = observation.topCandidates(1).first?.string { print(text) }
    }
} catch {
    fputs("Disclosure cover OCR failed\n", stderr)
    exit(1)
}
