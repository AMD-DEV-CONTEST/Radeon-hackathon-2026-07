export interface SerialPort {
  device: string;
  description: string;
  hwid: string;
  vid: number | null;
  pid: number | null;
  manufacturer: string | null;
}

export interface Device {
  device: string;
  description: string;
  hwid: string;
  vid: number | null;
  pid: number | null;
  manufacturer: string | null;
  type: 'serial' | 'ch34x' | 'cp210x' | 'ftdi' | 'arduino';
  friendly_name: string;
}

export interface DeviceState {
  x: number;
  y: number;
  z: number;
  roll: number;
  pitch: number;
  yaw: number;
  gripper: number;
  record_button: boolean;
  emergency_stop: boolean;
}

export interface DeviceStatus {
  connected: boolean;
  port?: string;
  baudrate?: number;
  protocol?: string;
  state?: DeviceState;
  message?: string;
}

export interface ScanResult {
  devices: Device[];
  connected_device: string | null;
}

export interface ConnectRequest {
  port: string;
  baudrate: number;
  protocol: 'json' | 'binary' | 'text';
}

export interface ConnectResponse {
  success: boolean;
  port?: string;
  baudrate?: number;
  protocol?: string;
  message?: string;
  error?: string;
}
