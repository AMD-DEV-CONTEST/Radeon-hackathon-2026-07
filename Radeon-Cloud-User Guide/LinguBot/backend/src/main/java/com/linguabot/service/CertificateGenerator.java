package com.linguabot.service;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.client.j2se.MatrixToImageWriter;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.lowagie.text.*;
import com.lowagie.text.Font;
import com.lowagie.text.Image;
import com.lowagie.text.pdf.*;
import org.springframework.stereotype.Service;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

@Service
public class CertificateGenerator {

    public byte[] generateCertificatePdf(String recipientName, String verificationCode, Instant issueDate) throws Exception {
        Document document = new Document(PageSize.A4.rotate(), 25, 25, 25, 25);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        PdfWriter writer = PdfWriter.getInstance(document, out);

        document.open();

        // 1. Draw elegant double border around the certificate page
        PdfContentByte canvas = writer.getDirectContent();
        float width = PageSize.A4.rotate().getWidth();
        float height = PageSize.A4.rotate().getHeight();
        
        // Outer thin border
        canvas.setLineWidth(2f);
        canvas.setColorStroke(new Color(139, 92, 246)); // primary violet
        canvas.rectangle(15, 15, width - 30, height - 30);
        canvas.stroke();

        // Inner thick border
        canvas.setLineWidth(4f);
        canvas.setColorStroke(new Color(99, 102, 241)); // indigo
        canvas.rectangle(20, 20, width - 40, height - 40);
        canvas.stroke();

        // 2. Setup Fonts
        Font logoFont = FontFactory.getFont(FontFactory.HELVETICA_BOLD, 9, Font.BOLD, Color.LIGHT_GRAY);
        Font titleFont = FontFactory.getFont(FontFactory.HELVETICA_BOLD, 24, Font.BOLD, new Color(79, 70, 229));
        Font subtitleFont = FontFactory.getFont(FontFactory.HELVETICA, 10, Font.ITALIC, Color.GRAY);
        Font nameFont = FontFactory.getFont(FontFactory.HELVETICA_BOLD, 22, Font.BOLD, new Color(30, 41, 59));
        Font courseFont = FontFactory.getFont(FontFactory.HELVETICA_BOLD, 14, Font.BOLD, new Color(139, 92, 246));
        Font bodyFont = FontFactory.getFont(FontFactory.HELVETICA, 9, Font.NORMAL, new Color(71, 85, 105));
        Font metaFont = FontFactory.getFont(FontFactory.COURIER, 8, Font.NORMAL, Color.GRAY);

        // 3. Document Content
        Paragraph logoParagraph = new Paragraph("LINGUABOT ACADEMY", logoFont);
        logoParagraph.setAlignment(Element.ALIGN_CENTER);
        logoParagraph.setSpacingAfter(6f);
        document.add(logoParagraph);

        Paragraph title = new Paragraph("CERTIFICATE OF COMPLETION", titleFont);
        title.setAlignment(Element.ALIGN_CENTER);
        title.setSpacingAfter(6f);
        document.add(title);

        Paragraph subtitle = new Paragraph("This is proudly presented to", subtitleFont);
        subtitle.setAlignment(Element.ALIGN_CENTER);
        subtitle.setSpacingAfter(6f);
        document.add(subtitle);

        Paragraph name = new Paragraph(recipientName.toUpperCase(), nameFont);
        name.setAlignment(Element.ALIGN_CENTER);
        name.setSpacingAfter(8f);
        document.add(name);

        Paragraph text = new Paragraph(
                "for demonstrating outstanding academic performance and dedication to language fluency\n" +
                "by successfully completing all curriculum requirements of the",
                bodyFont
        );
        text.setAlignment(Element.ALIGN_CENTER);
        text.setLeading(12f);
        text.setSpacingAfter(6f);
        document.add(text);

        Paragraph course = new Paragraph("LinguaBot AI Language Immersion Course", courseFont);
        course.setAlignment(Element.ALIGN_CENTER);
        course.setSpacingAfter(12f);
        document.add(course);

        // Generate QR code bytes representing verification URL
        String verificationUrl = "http://localhost:3000/verify/" + verificationCode;
        byte[] qrBytes = generateQrCodeBytes(verificationUrl, 65, 65);
        Image qrImage = Image.getInstance(qrBytes);
        qrImage.setAlignment(Element.ALIGN_CENTER);

        // Subtable for signatures and QR code
        PdfPTable table = new PdfPTable(3);
        table.setWidthPercentage(90);
        table.setWidths(new float[]{1f, 1.2f, 1f});

        // Left signature cell
        PdfPCell leftCell = new PdfPCell();
        leftCell.setBorder(Rectangle.NO_BORDER);
        leftCell.setHorizontalAlignment(Element.ALIGN_CENTER);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd").withZone(ZoneId.systemDefault());
        Paragraph dateVal = new Paragraph(formatter.format(issueDate), FontFactory.getFont(FontFactory.HELVETICA_BOLD, 10, Font.BOLD, Color.DARK_GRAY));
        dateVal.setAlignment(Element.ALIGN_CENTER);
        Paragraph dateLabel = new Paragraph("ISSUE DATE", metaFont);
        dateLabel.setAlignment(Element.ALIGN_CENTER);
        leftCell.addElement(dateVal);
        leftCell.addElement(dateLabel);

        // Center QR code cell
        PdfPCell centerCell = new PdfPCell();
        centerCell.setBorder(Rectangle.NO_BORDER);
        centerCell.setHorizontalAlignment(Element.ALIGN_CENTER);
        centerCell.addElement(qrImage);
        Paragraph qrLabel = new Paragraph("SCAN TO VERIFY DIPLOMA", metaFont);
        qrLabel.setAlignment(Element.ALIGN_CENTER);
        centerCell.addElement(qrLabel);

        // Right verification ID cell
        PdfPCell rightCell = new PdfPCell();
        rightCell.setBorder(Rectangle.NO_BORDER);
        rightCell.setHorizontalAlignment(Element.ALIGN_CENTER);
        Paragraph codeVal = new Paragraph(verificationCode, FontFactory.getFont(FontFactory.HELVETICA_BOLD, 10, Font.BOLD, Color.DARK_GRAY));
        codeVal.setAlignment(Element.ALIGN_CENTER);
        Paragraph codeLabel = new Paragraph("VERIFICATION ID", metaFont);
        codeLabel.setAlignment(Element.ALIGN_CENTER);
        rightCell.addElement(codeVal);
        rightCell.addElement(codeLabel);

        table.addCell(leftCell);
        table.addCell(centerCell);
        table.addCell(rightCell);

        document.add(table);

        document.close();
        return out.toByteArray();
    }

    private byte[] generateQrCodeBytes(String text, int width, int height) throws Exception {
        QRCodeWriter qrCodeWriter = new QRCodeWriter();
        BitMatrix bitMatrix = qrCodeWriter.encode(text, BarcodeFormat.QR_CODE, width, height);
        ByteArrayOutputStream pngOutputStream = new ByteArrayOutputStream();
        MatrixToImageWriter.writeToStream(bitMatrix, "PNG", pngOutputStream);
        return pngOutputStream.toByteArray();
    }
}
