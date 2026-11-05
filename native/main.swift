// MIT License. Native language services for LLPlayer; no upstream app code.
import Foundation
import Vision
import NaturalLanguage

func output(_ value: Any) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed])
    FileHandle.standardOutput.write(data)
}

do {
    guard CommandLine.arguments.count >= 2 else { throw NSError(domain: "Missing command", code: 1) }
    switch CommandLine.arguments[1] {
    case "tokens":
        let data = FileHandle.standardInput.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        let tokenizer = NLTokenizer(unit: .word)
        tokenizer.string = text
        if let language = NLLanguageRecognizer.dominantLanguage(for: text) { tokenizer.setLanguage(language) }
        var tokens: [[String: Any]] = []
        tokenizer.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
            tokens.append(["text": String(text[range]),
                           "start": text[..<range.lowerBound].unicodeScalars.count,
                           "end": text[..<range.upperBound].unicodeScalars.count])
            return true
        }
        try output(tokens)
    case "ocr":
        guard CommandLine.arguments.count >= 3 else { throw NSError(domain: "Missing image", code: 1) }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        if #available(macOS 13.0, *) { request.automaticallyDetectsLanguage = true }
        if CommandLine.arguments.count >= 4 && CommandLine.arguments[3] != "auto" {
            request.recognitionLanguages = CommandLine.arguments[3].components(separatedBy: "+")
        }
        let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[2]))
        try handler.perform([request])
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        try output(lines.joined(separator: "\n"))
    default:
        throw NSError(domain: "Unknown command", code: 1)
    }
} catch {
    FileHandle.standardError.write(String(describing: error).data(using: .utf8)!)
    exit(1)
}
