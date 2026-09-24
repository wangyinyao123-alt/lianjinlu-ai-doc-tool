// 炼金炉 Windows 启动器。
//
// 该程序只负责定位同目录下的内置 Python、启动 app.py，并在服务就绪后
// 打开浏览器。应用数据仍由 app.py 保存在安装目录旁的 data/ 中。
package main

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

const (
	appURL         = "http://127.0.0.1:8765"
	serverHealth   = appURL + "/api/health"
	createNoWindow = 0x08000000
)

func message(title, body string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")
	titlePtr, _ := syscall.UTF16PtrFromString(title)
	bodyPtr, _ := syscall.UTF16PtrFromString(body)
	messageBox.Call(0, uintptr(unsafe.Pointer(bodyPtr)), uintptr(unsafe.Pointer(titlePtr)), 0x10)
}

func serviceReady() bool {
	client := &http.Client{Timeout: 350 * time.Millisecond}
	response, err := client.Get(serverHealth)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode == http.StatusOK
}

func openBrowser() error {
	return exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", appURL).Run()
}

func main() {
	executable, err := os.Executable()
	if err != nil {
		message("炼金炉", "无法定位应用目录。")
		return
	}
	root := filepath.Dir(executable)
	python := filepath.Join(root, "python.exe")
	app := filepath.Join(root, "app.py")
	if _, err := os.Stat(python); err != nil {
		message("炼金炉", fmt.Sprintf("未找到内置 Python：%s\n请确认已完整解压 Windows 安装包。", python))
		return
	}
	if _, err := os.Stat(app); err != nil {
		message("炼金炉", fmt.Sprintf("未找到应用文件：%s", app))
		return
	}

	if !serviceReady() {
		logPath := filepath.Join(root, "data", "launcher.log")
		_ = os.MkdirAll(filepath.Dir(logPath), 0o755)
		logFile, logErr := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if logErr != nil {
			message("炼金炉", "无法创建启动日志，应用未启动。")
			return
		}
		defer logFile.Close()

		command := exec.Command(python, app)
		command.Dir = root
		command.Stdout = logFile
		command.Stderr = logFile
		command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: createNoWindow}
		if err := command.Start(); err != nil {
			message("炼金炉", "启动本地服务失败：\n"+err.Error())
			return
		}
	}

	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if serviceReady() {
			_ = openBrowser()
			return
		}
		time.Sleep(250 * time.Millisecond)
	}
	message("炼金炉", "本地服务启动超时。\n请查看 data\\launcher.log 获取详细信息。")
}
