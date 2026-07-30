/**
 * 摄像头扫码弹窗。
 *
 * 用 jsQR 在动画帧循环里对视频帧解码，纯前端完成，不新增后端接口。
 *
 * 关键约束：getUserMedia 只在安全上下文可用 —— localhost 算安全，
 * 但通过局域网 IP 以 http 打开时浏览器会直接拒绝授权。这种情况下
 * 静默失败最难排查，所以这里显式判断并给出可操作的提示。
 */

import { Alert, Button, Modal, Select, Space, Typography } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import jsQRImport from 'jsqr'
import { extractCouponCode } from '../utils/couponCode'

type Decoder = typeof jsQRImport

// jsqr 发布的是 webpack UMD 产物，不同打包器下拿到的可能是函数本身，
// 也可能是 { default: 函数 }，两种都兜住，避免升级打包器时炸掉。
const decodeQr: Decoder =
  typeof jsQRImport === 'function'
    ? jsQRImport
    : (jsQRImport as unknown as { default: Decoder }).default

/** 解码用的采样边长上限：整帧解码在 1080p 下明显卡顿，缩到 720 已足够识别 */
const SAMPLE_MAX = 720
/** 解码节流间隔（毫秒）。每帧都解码会把 CPU 吃满，10fps 的手感已经很跟手 */
const DECODE_INTERVAL = 100

function describeError(e: unknown): string {
  const name = e instanceof Error ? e.name : ''
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return '摄像头权限被拒绝。请在浏览器地址栏的权限设置里允许使用摄像头，然后重试。'
    case 'NotFoundError':
    case 'OverconstrainedError':
      return '没有检测到可用的摄像头。'
    case 'NotReadableError':
      return '摄像头被其他程序占用，请关闭正在使用摄像头的应用后重试。'
    default:
      return `无法打开摄像头：${e instanceof Error ? e.message : String(e)}`
  }
}

export function QrScanModal({
  open,
  onCancel,
  onDetect,
}: {
  open: boolean
  onCancel: () => void
  /** 识别到合法券码时回调。回调后弹窗即关闭，摄像头释放 */
  onDetect: (code: string) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef(0)
  const lastDecodeRef = useRef(0)
  // 命中后要立刻停掉循环，否则同一张券会连续触发多次查验
  const settledRef = useRef(false)

  // 放进 ref：父组件通常直接传内联箭头函数，若让它进入 useCallback 依赖，
  // 父组件每次重渲染都会重启摄像头。
  const onDetectRef = useRef(onDetect)
  onDetectRef.current = onDetect

  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState<string | undefined>()

  const stop = useCallback(() => {
    cancelAnimationFrame(rafRef.current)
    rafRef.current = 0
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    const video = videoRef.current
    if (video) video.srcObject = null
    setScanning(false)
  }, [])

  const tick = useCallback(() => {
    rafRef.current = requestAnimationFrame(tick)
    if (settledRef.current) return

    const video = videoRef.current
    if (!video || video.readyState < video.HAVE_CURRENT_DATA) return

    const now = performance.now()
    if (now - lastDecodeRef.current < DECODE_INTERVAL) return
    lastDecodeRef.current = now

    const vw = video.videoWidth
    const vh = video.videoHeight
    if (!vw || !vh) return

    const scale = Math.min(1, SAMPLE_MAX / Math.max(vw, vh))
    const w = Math.round(vw * scale)
    const h = Math.round(vh * scale)

    const canvas = (canvasRef.current ??= document.createElement('canvas'))
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w
      canvas.height = h
    }
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return
    ctx.drawImage(video, 0, 0, w, h)

    const frame = ctx.getImageData(0, 0, w, h)
    const result = decodeQr(frame.data, w, h, { inversionAttempts: 'dontInvert' })
    if (!result) return

    const code = extractCouponCode(result.data)
    if (!code) {
      // 扫到了二维码但不是券码（比如顺手扫了个付款码），提示后继续扫
      setWarning(`识别到二维码，但不是有效券码：${result.data.slice(0, 40)}`)
      return
    }

    settledRef.current = true
    stop()
    onDetectRef.current(code)
  }, [stop])

  const start = useCallback(
    async (id?: string) => {
      setError(null)
      setWarning(null)
      settledRef.current = false

      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setError(
          '当前页面不是安全上下文，浏览器不允许访问摄像头。请用 http://localhost:5173 打开，' +
            '或为站点配置 HTTPS 后再使用扫码；也可以手工输入券码。',
        )
        return
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          // 门店场景优先用后置摄像头，桌面机没有后置会自动回退到唯一的那颗
          video: id ? { deviceId: { exact: id } } : { facingMode: { ideal: 'environment' } },
          audio: false,
        })
        streamRef.current = stream
        const video = videoRef.current
        if (!video) {
          // 理论上弹窗内容已挂载，真出现就明确报错，别留个转不动的"启动中"
          stream.getTracks().forEach((t) => t.stop())
          setError('画面元素尚未就绪，请关闭弹窗后重试。')
          return
        }
        video.srcObject = stream
        await video.play()
        setScanning(true)

        // 设备标签要等授权之后才可读，所以放在 getUserMedia 成功之后再枚举
        const list = (await navigator.mediaDevices.enumerateDevices()).filter(
          (d) => d.kind === 'videoinput',
        )
        setDevices(list)
        setDeviceId(stream.getVideoTracks()[0]?.getSettings().deviceId ?? id)

        cancelAnimationFrame(rafRef.current)
        lastDecodeRef.current = 0
        rafRef.current = requestAnimationFrame(tick)
      } catch (e) {
        stop()
        setError(describeError(e))
      }
    },
    [stop, tick],
  )

  // 只按 open 开关摄像头：切换镜头走 switchCamera 自行重启，
  // 若把 deviceId / start 放进依赖会导致摄像头被反复开关。
  useEffect(() => {
    if (!open) return
    void start()
    return stop
  }, [open, start, stop])

  const switchCamera = (id: string) => {
    setDeviceId(id)
    stop()
    void start(id)
  }

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      title="扫码录入券码"
      footer={
        <Space>
          {error && (
            <Button
              onClick={() => {
                void start(deviceId)
              }}
            >
              重试
            </Button>
          )}
          <Button onClick={onCancel}>取消</Button>
        </Space>
      }
      maskClosable={false}
      width={520}
    >
      {error ? (
        <Alert type="error" showIcon message="摄像头不可用" description={error} />
      ) : (
        <>
          <div className="qr-scan">
            <video ref={videoRef} className="qr-scan__video" playsInline muted />
            <div className="qr-scan__frame" />
            {!scanning && <div className="qr-scan__hint">正在启动摄像头…</div>}
          </div>

          <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '12px 0 0' }}>
            把顾客手机上的券码二维码对准取景框，识别成功后会自动查验。
          </Typography.Paragraph>

          {warning && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 8 }}
              message={warning}
              closable
              onClose={() => setWarning(null)}
            />
          )}

          {devices.length > 1 && (
            <Select
              size="small"
              style={{ width: '100%', marginTop: 8 }}
              value={deviceId}
              onChange={switchCamera}
              options={devices.map((d, i) => ({
                value: d.deviceId,
                label: d.label || `摄像头 ${i + 1}`,
              }))}
            />
          )}
        </>
      )}
    </Modal>
  )
}
