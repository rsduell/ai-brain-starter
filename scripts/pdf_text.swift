// Print a PDF's text, one `=== page N ===` marker per page. Used by asset_text.py.
// Usage: swift scripts/pdf_text.swift <file.pdf>
import Foundation
import PDFKit

guard CommandLine.arguments.count == 2,
      let doc = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])) else {
    FileHandle.standardError.write("usage: swift pdf_text.swift <file.pdf> (or the PDF could not be opened)\n".data(using: .utf8)!)
    exit(1)
}
for i in 0..<doc.pageCount {
    print("=== page \(i + 1) ===")
    print(doc.page(at: i)?.string ?? "")
}
