import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let arguments = Array(CommandLine.arguments.dropFirst())
guard arguments.count == 3,
      let pageNumber = Int(arguments[1]),
      let document = CGPDFDocument(URL(fileURLWithPath: arguments[0]) as CFURL),
      let page = document.page(at: pageNumber) else {
  fputs("Usage: render-pdf-page <input.pdf> <page-number> <output.png>\n", stderr)
  exit(1)
}

let box = page.getBoxRect(.mediaBox)
let scale: CGFloat = 4
let width = Int(box.width * scale)
let height = Int(box.height * scale)
guard let context = CGContext(
  data: nil,
  width: width,
  height: height,
  bitsPerComponent: 8,
  bytesPerRow: 0,
  space: CGColorSpaceCreateDeviceRGB(),
  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
) else {
  fputs("Cannot create render context\n", stderr)
  exit(1)
}

context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: width, height: height))
context.concatenate(page.getDrawingTransform(.mediaBox, rect: CGRect(x: 0, y: 0, width: width, height: height), rotate: 0, preserveAspectRatio: true))
context.drawPDFPage(page)

guard let image = context.makeImage(),
      let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: arguments[2]) as CFURL, UTType.png.identifier as CFString, 1, nil) else {
  fputs("Cannot write PNG\n", stderr)
  exit(1)
}
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else {
  fputs("Cannot finalize PNG\n", stderr)
  exit(1)
}
