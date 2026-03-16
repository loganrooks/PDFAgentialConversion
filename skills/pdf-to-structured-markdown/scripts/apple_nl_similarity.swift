#!/usr/bin/env swift

import Foundation
import NaturalLanguage

struct TextItem: Decodable {
    let id: String
    let text: String
}

struct RequestPayload: Decodable {
    let documents: [TextItem]
    let queries: [TextItem]
}

struct ResponsePayload: Encodable {
    let backend: String
    let dimension: Int
    let similarities: [String: [String: Double]]
}

func readStdin() throws -> Data {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    if input.isEmpty {
        throw NSError(domain: "apple_nl_similarity", code: 1, userInfo: [
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

func cosine(_ left: [Double], _ right: [Double]) -> Double {
    guard left.count == right.count else { return 0.0 }
    return zip(left, right).reduce(0.0) { partial, pair in
        partial + (pair.0 * pair.1)
    }
}

do {
    guard #available(macOS 12.0, *) else {
        throw NSError(domain: "apple_nl_similarity", code: 2, userInfo: [
            NSLocalizedDescriptionKey: "NaturalLanguage sentence embeddings require macOS 12 or newer."
        ])
    }

    guard let embedding = NLEmbedding.sentenceEmbedding(for: .english) else {
        throw NSError(domain: "apple_nl_similarity", code: 3, userInfo: [
            NSLocalizedDescriptionKey: "NaturalLanguage sentence embedding is unavailable on this machine."
        ])
    }

    let payload = try JSONDecoder().decode(RequestPayload.self, from: readStdin())
    let documentEntries: [(String, [Double])] = payload.documents.compactMap { item in
        guard let vector = embed(item.text, using: embedding) else {
            return nil
        }
        return (item.id, vector)
    }
    let queryEntries: [(String, [Double])] = payload.queries.compactMap { item in
        guard let vector = embed(item.text, using: embedding) else {
            return nil
        }
        return (item.id, vector)
    }
    let documentVectors = Dictionary(uniqueKeysWithValues: documentEntries)
    let queryVectors = Dictionary(uniqueKeysWithValues: queryEntries)

    var similarities: [String: [String: Double]] = [:]
    for query in payload.queries {
        guard let queryVector = queryVectors[query.id] else {
            similarities[query.id] = [:]
            continue
        }
        var scores: [String: Double] = [:]
        for document in payload.documents {
            guard let documentVector = documentVectors[document.id] else {
                continue
            }
            scores[document.id] = cosine(queryVector, documentVector)
        }
        similarities[query.id] = scores
    }

    let response = ResponsePayload(
        backend: "NaturalLanguage.sentenceEmbedding",
        dimension: embedding.dimension,
        similarities: similarities
    )
    let encoded = try JSONEncoder().encode(response)
    FileHandle.standardOutput.write(encoded)
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
