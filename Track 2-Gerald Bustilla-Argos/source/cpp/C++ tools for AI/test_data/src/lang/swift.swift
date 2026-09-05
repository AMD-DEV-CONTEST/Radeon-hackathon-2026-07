import Foundation

class ImageFingerprint {
    var perceptualHash: UInt64
    var base64Hash: String
    
    init(data: [UInt8]) {
        self.perceptualHash = Self.computePerceptualHash(data)
        self.base64Hash = Self.base64Encode(data)
    }
}
