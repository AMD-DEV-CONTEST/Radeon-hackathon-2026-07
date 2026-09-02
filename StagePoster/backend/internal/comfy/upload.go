package comfy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

type uploadImageResponse struct {
	Name      string `json:"name"`
	Subfolder string `json:"subfolder"`
	Type      string `json:"type"`
}

// UploadImage 把一张本地图片放进 ComfyUI 的 input 目录，返回 LoadImage 能用的
// 名字（带 subfolder 前缀）。
//
// 参考图必须先到 ComfyUI 那边，LoadImage 才看得见它。后端和 ComfyUI 虽然同机，
// 但直接往对方的 input 目录写文件属于跨服务改文件系统 —— 用它自己的上传接口，
// 换个部署（容器 / 远端 ComfyUI）也不会坏。
func (c *Client) UploadImage(
	ctx context.Context,
	sourcePath string,
	targetName string,
) (string, error) {
	file, err := os.Open(sourcePath)
	if err != nil {
		return "", fmt.Errorf("open reference image: %w", err)
	}
	defer file.Close()

	if targetName == "" {
		targetName = filepath.Base(sourcePath)
	}

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	part, err := writer.CreateFormFile("image", targetName)
	if err != nil {
		return "", fmt.Errorf("build upload request: %w", err)
	}

	if _, err := io.Copy(part, file); err != nil {
		return "", fmt.Errorf("copy reference image: %w", err)
	}

	// 同一张素材反复用时覆盖即可，不要在 input 目录里堆出
	// reference (1).png、reference (2).png。
	if err := writer.WriteField("overwrite", "true"); err != nil {
		return "", fmt.Errorf("build upload request: %w", err)
	}

	if err := writer.Close(); err != nil {
		return "", fmt.Errorf("finalize upload request: %w", err)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.baseURL+"/upload/image",
		bytes.NewReader(body.Bytes()),
	)
	if err != nil {
		return "", err
	}

	request.Header.Set(
		"Content-Type",
		writer.FormDataContentType(),
	)

	response, err := c.http.Do(request)
	if err != nil {
		return "", fmt.Errorf("upload reference image: %w", err)
	}
	defer response.Body.Close()

	raw, err := io.ReadAll(
		io.LimitReader(response.Body, 1*1024*1024),
	)
	if err != nil {
		return "", fmt.Errorf("read upload response: %w", err)
	}

	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return "", fmt.Errorf(
			"ComfyUI upload returned HTTP %d: %s",
			response.StatusCode,
			string(raw),
		)
	}

	var result uploadImageResponse
	if err := json.Unmarshal(raw, &result); err != nil {
		return "", fmt.Errorf(
			"decode upload response: %w",
			err,
		)
	}

	if result.Name == "" {
		return "", fmt.Errorf(
			"ComfyUI upload response has no name: %s",
			string(raw),
		)
	}

	if result.Subfolder != "" {
		return result.Subfolder + "/" + result.Name, nil
	}

	return strings.TrimSpace(result.Name), nil
}
