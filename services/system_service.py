"""Windows 系统音量与锁屏适配；COM 由任务队列按线程初始化。"""

from app.utils import is_windows


class VolumeService:
    def _control(self):
        if not is_windows():
            raise RuntimeError("音量控制仅支持 Windows")
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        device = AudioUtilities.GetSpeakers()
        if device is None:
            raise RuntimeError("未找到音频输出设备")
        if hasattr(device, "EndpointVolume"):
            return device.EndpointVolume
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)

    def mute(self):
        self._control().SetMute(1, None)
        return "已静音。"

    def unmute(self):
        self._control().SetMute(0, None)
        return "已取消静音。"

    def volume_up(self, step=0.1):
        control = self._control()
        value = min(1.0, control.GetMasterVolumeLevelScalar() + step)
        control.SetMasterVolumeLevelScalar(value, None)
        return f"音量已调高至 {value:.0%}。"

    def volume_down(self, step=0.1):
        control = self._control()
        value = max(0.0, control.GetMasterVolumeLevelScalar() - step)
        control.SetMasterVolumeLevelScalar(value, None)
        return f"音量已调低至 {value:.0%}。"


class SystemCommandService:
    def lock_screen(self):
        if not is_windows():
            raise RuntimeError("锁屏仅支持 Windows")
        import ctypes

        if not ctypes.windll.user32.LockWorkStation():
            raise OSError("锁屏调用失败")
        return "已锁定屏幕。"
