// Copyright 2026 Xenix contributors
// SPDX-License-Identifier: Apache-2.0

#include <fcntl.h>
#include <io.h>

#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "src/pipelines/ocr/pipeline.h"
#include "third_party/nlohmann/json.hpp"

namespace {

using json = nlohmann::json;

constexpr std::uint32_t kProtocolVersion = 2;
constexpr std::uint32_t kMaxMessageBytes = 16U * 1024U * 1024U;
constexpr const char *kRuntimeId =
    "paddle-inference-3.3.0-paddleocr-3.7.0-win-x64";
constexpr const char *kModelPackId = "pp-ocrv6-medium-zh-en-1";

const std::unordered_map<std::string, std::string> &XenixPipelineConfig() {
  // Flattened from PaddleOCR v3.7.0's deploy/cpp_infer/src/configs/OCR.yaml.
  // The caller overrides the optional document and textline stages below.
  static const std::unordered_map<std::string, std::string> config = {
      {"pipeline_name", "OCR"},
      {"text_type", "general"},
      {"use_doc_preprocessor", "True"},
      {"use_textline_orientation", "True"},
      {"SubPipelines.DocPreprocessor.pipeline_name", "doc_preprocessor"},
      {"SubPipelines.DocPreprocessor.use_doc_orientation_classify", "True"},
      {"SubPipelines.DocPreprocessor.use_doc_unwarping", "True"},
      {"SubPipelines.DocPreprocessor.SubModules.DocOrientationClassify."
       "module_name",
       "doc_text_orientation"},
      {"SubPipelines.DocPreprocessor.SubModules.DocOrientationClassify."
       "model_name",
       "PP-LCNet_x1_0_doc_ori"},
      {"SubPipelines.DocPreprocessor.SubModules.DocOrientationClassify."
       "model_dir",
       "null"},
      {"SubPipelines.DocPreprocessor.SubModules.DocUnwarping.module_name",
       "image_unwarping"},
      {"SubPipelines.DocPreprocessor.SubModules.DocUnwarping.model_name",
       "UVDoc"},
      {"SubPipelines.DocPreprocessor.SubModules.DocUnwarping.model_dir",
       "null"},
      {"SubModules.TextDetection.module_name", "text_detection"},
      {"SubModules.TextDetection.model_name", "PP-OCRv6_medium_det"},
      {"SubModules.TextDetection.model_dir", "null"},
      {"SubModules.TextDetection.limit_side_len", "64"},
      {"SubModules.TextDetection.limit_type", "min"},
      {"SubModules.TextDetection.max_side_limit", "4000"},
      {"SubModules.TextDetection.thresh", "0.3"},
      {"SubModules.TextDetection.box_thresh", "0.6"},
      {"SubModules.TextDetection.unclip_ratio", "1.5"},
      {"SubModules.TextLineOrientation.module_name", "textline_orientation"},
      {"SubModules.TextLineOrientation.model_name",
       "PP-LCNet_x1_0_textline_ori"},
      {"SubModules.TextLineOrientation.model_dir", "null"},
      {"SubModules.TextLineOrientation.batch_size", "6"},
      {"SubModules.TextRecognition.module_name", "text_recognition"},
      {"SubModules.TextRecognition.model_name", "PP-OCRv6_medium_rec"},
      {"SubModules.TextRecognition.model_dir", "null"},
      {"SubModules.TextRecognition.batch_size", "6"},
      {"SubModules.TextRecognition.score_thresh", "0.0"},
  };
  return config;
}

class Engine {
public:
  json Initialize(const json &arguments) {
    if (pipeline_) {
      throw std::invalid_argument("engine already initialized");
    }
    if (arguments.value("model_pack_id", "") != kModelPackId) {
      throw std::invalid_argument("model pack identity mismatch");
    }
    const auto detection = arguments.at("detection_model_path").get<std::string>();
    const auto recognition =
        arguments.at("recognition_model_path").get<std::string>();
    if (detection.empty() || recognition.empty()) {
      throw std::invalid_argument("model path missing");
    }

    OCRPipelineParams params;
    params.text_detection_model_name = "PP-OCRv6_medium_det";
    params.text_detection_model_dir = detection;
    params.text_recognition_model_name = "PP-OCRv6_medium_rec";
    params.text_recognition_model_dir = recognition;
    params.paddlex_config =
        Utility::PaddleXConfigVariant(XenixPipelineConfig());
    params.use_doc_orientation_classify = false;
    params.use_doc_unwarping = false;
    params.use_textline_orientation = false;
    params.enable_mkldnn = false;
    params.device = "cpu";
    params.precision = "fp32";
    params.cpu_threads = 8;
    params.thread_num = 1;
    pipeline_.reset(new _OCRPipeline(params));
    return {{"initialized", true}};
  }

  json Recognize(const json &arguments) {
    if (!pipeline_) {
      throw std::logic_error("engine not initialized");
    }
    const auto image_path = arguments.at("image_path").get<std::string>();
    if (image_path.empty()) {
      throw std::invalid_argument("image path missing");
    }
    pipeline_->Predict({image_path});
    const auto results = pipeline_->PipelineResult();
    if (results.size() != 1) {
      throw std::runtime_error("unexpected OCR result count");
    }
    const auto &result = results.front();
    if (result.rec_texts.size() != result.rec_scores.size() ||
        result.rec_texts.size() != result.rec_polys.size()) {
      throw std::runtime_error("inconsistent OCR result vectors");
    }

    json regions = json::array();
    for (std::size_t index = 0; index < result.rec_texts.size(); ++index) {
      json polygon = json::array();
      for (const auto &point : result.rec_polys[index]) {
        polygon.push_back({point.x, point.y});
      }
      regions.push_back({{"text", result.rec_texts[index]},
                         {"confidence", result.rec_scores[index]},
                         {"polygon", polygon}});
    }
    return {{"regions", regions}};
  }

  bool initialized() const { return pipeline_ != nullptr; }

private:
  std::unique_ptr<_OCRPipeline> pipeline_;
};

bool ReadExact(char *destination, std::size_t size) {
  std::cin.read(destination, static_cast<std::streamsize>(size));
  return static_cast<std::size_t>(std::cin.gcount()) == size;
}

bool ReadFrame(json *message) {
  unsigned char header[4] = {};
  if (!ReadExact(reinterpret_cast<char *>(header), sizeof(header))) {
    return false;
  }
  const std::uint32_t size =
      (static_cast<std::uint32_t>(header[0]) << 24U) |
      (static_cast<std::uint32_t>(header[1]) << 16U) |
      (static_cast<std::uint32_t>(header[2]) << 8U) |
      static_cast<std::uint32_t>(header[3]);
  if (size < 2 || size > kMaxMessageBytes) {
    throw std::runtime_error("request frame length out of bounds");
  }
  std::string payload(size, '\0');
  if (!ReadExact(&payload[0], payload.size())) {
    throw std::runtime_error("truncated request frame");
  }
  *message = json::parse(payload);
  return true;
}

void WriteFrame(const json &message) {
  const std::string payload = message.dump();
  if (payload.empty() || payload.size() > kMaxMessageBytes) {
    throw std::runtime_error("response frame length out of bounds");
  }
  const auto size = static_cast<std::uint32_t>(payload.size());
  const unsigned char header[4] = {
      static_cast<unsigned char>((size >> 24U) & 0xffU),
      static_cast<unsigned char>((size >> 16U) & 0xffU),
      static_cast<unsigned char>((size >> 8U) & 0xffU),
      static_cast<unsigned char>(size & 0xffU),
  };
  std::cout.write(reinterpret_cast<const char *>(header), sizeof(header));
  std::cout.write(payload.data(), static_cast<std::streamsize>(payload.size()));
  std::cout.flush();
}

json Success(const std::string &request_id, json result) {
  return {{"protocol_version", kProtocolVersion},
          {"request_id", request_id},
          {"ok", true},
          {"result", std::move(result)}};
}

json Failure(const std::string &request_id, const char *reason_code) {
  return {{"protocol_version", kProtocolVersion},
          {"request_id", request_id},
          {"ok", false},
          {"reason_code", reason_code}};
}

int RunProtocol() {
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
  std::ios::sync_with_stdio(false);
  Engine engine;
  while (true) {
    json request;
    if (!ReadFrame(&request)) {
      return 0;
    }
    std::string request_id;
    try {
      if (!request.is_object() ||
          request.at("protocol_version").get<std::uint32_t>() !=
              kProtocolVersion ||
          !request.at("request_id").is_string() ||
          !request.at("operation").is_string() ||
          !request.at("arguments").is_object()) {
        throw std::invalid_argument("invalid request envelope");
      }
      request_id = request.at("request_id").get<std::string>();
      const auto operation = request.at("operation").get<std::string>();
      const auto &arguments = request.at("arguments");
      if (operation == "version") {
        WriteFrame(Success(request_id,
                           {{"protocol_version", kProtocolVersion},
                            {"runtime_id", kRuntimeId},
                            {"engine", "paddle-inference"},
                            {"engine_version", "3.3.0"},
                            {"architecture", "windows-x86_64"}}));
      } else if (operation == "initialize") {
        WriteFrame(Success(request_id, engine.Initialize(arguments)));
      } else if (operation == "self_test") {
        WriteFrame(Success(request_id, {{"success", engine.initialized()}}));
      } else if (operation == "recognize") {
        WriteFrame(Success(request_id, engine.Recognize(arguments)));
      } else if (operation == "shutdown") {
        WriteFrame(Success(request_id, {{"shutdown", true}}));
        return 0;
      } else {
        WriteFrame(Failure(request_id, "knowledge_ocr_operation_unsupported"));
      }
    } catch (const std::invalid_argument &) {
      WriteFrame(Failure(request_id, "knowledge_ocr_request_invalid"));
    } catch (const json::exception &) {
      WriteFrame(Failure(request_id, "knowledge_ocr_request_invalid"));
    } catch (const std::exception &error) {
      std::cerr << "Native OCR request failed: " << error.what() << std::endl;
      WriteFrame(Failure(request_id, "knowledge_ocr_inference_failed"));
    }
  }
}

} // namespace

int main(int argc, char **argv) {
  if (argc != 2 || std::string(argv[1]) != "--stdio") {
    std::cerr << "Usage: xenix-ocr.exe --stdio" << std::endl;
    return 2;
  }
  try {
    return RunProtocol();
  } catch (const std::exception &error) {
    std::cerr << "Native OCR protocol failed: " << error.what() << std::endl;
    return 3;
  }
}
