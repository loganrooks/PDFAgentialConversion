#!/usr/bin/env swift

import Foundation
import NaturalLanguage

struct TextItem: Decodable {
    let id: String
    let text: String
}

struct RequestPayload: Decodable {
    let items: [TextItem]
}

struct ResponsePayload: Encodable {
    let backend: String
    let dimension: Int
    let embeddings: [String: [Double]]
}

func readStdin() throws -> Data {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    if input.isEmpty {
        throw NSError(domain: "apple_nl_embed", code: 1, userInfo: [
            NSLocalizedDescriptionKey: "Expected JSON payload on stdin."
        ])
    }
    return input
}

func normalized(_ vector: [Double]) -> [Double] {
    let norm = sqrt(vector.reduce(0.0) { $0 + ($1 * $1) })
    guard norm > 0 else { return vector }
    return vector.map { $0 / norm }
}

func average(_ vectors: [[Double]]) -> [Double]? {
    guard let first = vectors.first else { return nil }
    var totals = Array(repeating: 0.0, count: first.count)
    for vector in vectors {
        guard vector.count == first.count else { continue }
        for (index, value) in vector.enumerated() {
            totals[index] += value
        }
    }
    let divisor = Double(vectors.count)
    guard divisor > 0 else { return nil }
    return totals.map { $0 / divisor }
}

func sentenceLikeSegments(from text: String, segmentLimit: Int = 420, maxSegments: Int = 8) -> [String] {
    let cleaned = text.replacingOccurrences(of: "\r\n", with: "\n")
    let paragraphs = cleaned
        .components(separatedBy: "\n\n")
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }

    if paragraphs.isEmpty {
        return []
    }

    var segments: [String] = []
    let tokenizer = NLTokenizer(unit: .sentence)
    for paragraph in paragraphs {
        tokenizer.string = paragraph
        tokenizer.enumerateTokens(in: paragraph.startIndex..<paragraph.endIndex) { range, _ in
            let sentence = paragraph[range].trimmingCharacters(in: .whitespacesAndNewlines)
            if sentence.isEmpty {
                return true
            }
            if sentence.count <= segmentLimit {
                segments.append(String(sentence))
            } else {
                var start = sentence.startIndex
                while start < sentence.endIndex {
                    let end = sentence.index(start, offsetBy: segmentLimit, limitedBy: sentence.endIndex) ?? sentence.endIndex
                    segments.append(String(sentence[start..<end]))
                    start = end
                }
            }
            return segments.count < maxSegments
        }
        if segments.count >= maxSegments {
            break
        }
    }
    return Array(segments.prefix(maxSegments))
}

func embed(_ text: String, using embedding: NLEmbedding) -> [Double]? {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }

    if let direct = embedding.vector(for: trimmed) {
        return normalized(direct)
    }

    let segments = sentenceLikeSegments(from: trimmed)
    let vectors = segments.compactMap { embedding.vector(for: $0) }.map(normalized)
    guard let averaged = average(vectors) else {
        return nil
    }
    return normalized(averaged)
}

do {
    guard #available(macOS 12.0, *) else {
        throw NSError(domain: "apple_nl_embed", code: 2, userInfo: [
            NSLocalizedDescriptionKey: "NaturalLanguage sentence embeddings require macOS 12 or newer."
        ])
    }

    guard let embedding = NLEmbedding.sentenceEmbedding(for: .english) else {
        throw NSError(domain: "apple_nl_embed", code: 3, userInfo: [
            NSLocalizedDescriptionKey: "NaturalLanguage sentence embedding is unavailable on this machine."
        ])
    }

    let payload = try JSONDecoder().decode(RequestPayload.self, from: readStdin())
    var embeddings: [String: [Double]] = [:]
    embeddings.reserveCapacity(payload.items.count)

    for item in payload.items {
        if let vector = embed(item.text, using: embedding) {
            embeddings[item.id] = vector
        }
    }

    let response = ResponsePayload(
        backend: "NaturalLanguage.sentenceEmbedding",
        dimension: embedding.dimension,
        embeddings: embeddings
    )
    let encoded = try JSONEncoder().encode(response)
    FileHandle.standardOutput.write(encoded)
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
