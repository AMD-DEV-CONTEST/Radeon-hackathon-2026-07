const express = require('express');
const multer  = require('multer');
const path = require('path');
const app = express();
const PORT = 8000;

// Configure file storage boundary rules and disk engines safely
const storageEngine = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, './uploads/'); // Make sure this folder exists inside your filesystem directory
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, file.fieldname + '-' + uniqueSuffix + path.extname(file.originalname));
  }
});

const uploadMiddleware = multer({ 
  storage: storageEngine,
  limits: { fileSize: 20 * 1024 * 1024 } // Strict 20MB file filter cutoff limits block
});

// Serve frontend visual asset layers uniformly
app.use(express.static(__dirname + '/'));

/* 
   📡 POST API Generation Pipeline Interface Link.
   Intercepts FormData array structures matching target identifier 'image_asset'.
*/
app.post('/api/v1/generate-story', uploadMiddleware.single('image_asset'), (req, res) => {
  try {
    const uploadedFileMetadata = req.file;
    if (!uploadedFileMetadata) {
      return res.status(400).json({ status: "error", message: "Missing upload multi-part image target asset payload." });
    }

    console.log(`📥 [API Engine Request]: Received file data packet: ${uploadedFileMetadata.filename}`);

    // Mock an artificial 2-second processing delay to let the UI display loading animations smoothly
    setTimeout(() => {
      
      // This response object matches the properties that your frontend app.js expects to read
      const secureApiResponsePayload = {
        status: "success",
        timestamp: new Date().toISOString(),
        model_metrics_scope: ["LLM-Alpha", "Vision-Pro"],
        generated_story: "In the year 2050, classrooms are no longer confined by physical walls. AI-powered teachers deliver personalized learning through immersive holographic experiences, making education accessible, engaging, and fun for everyone regardless of their location..."
      };

      // Dispatch JSON parameters package straight back down through client request tracks
      res.status(200).json(secureApiResponsePayload);
      
    }, 2000);

  } catch (serverFailureException) {
    console.error("❌ [Internal Processing Server Crash Exception]:", serverFailureException);
    res.status(500).json({ status: "fail", error_code: 500, message: "AI transaction network pipeline routing stall." });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 [Picture Alive AI Server Engine Running]: Connected safely on link: http://localhost:${PORT}`);
});
