/**
 * API 封装层：组件统一 import { api }，不直接 import wailsjs。
 * 后端方法签名变更时只改这一个文件（见 dev-skill frontend-patterns.md）。
 *
 * wailsjs 目录由 wails dev / wails build 自动生成。
 */
import {
  GetSettings,
  SetSettings,
  StartServer,
  StopServer,
  GetServerStatus,
  ListNodes,
} from '../../wailsjs/go/main/App'
import type { main } from '../../wailsjs/go/models'

export type Settings = main.Settings
export type SettingsResult = main.SettingsResult
export type StartResult = main.StartResult
export type StopResult = main.StopResult
export type ServerStatus = main.ServerStatus
export type NodeSpec = main.NodeSpec

export const api = {
  getSettings: GetSettings,
  setSettings: SetSettings,
  startServer: StartServer,
  stopServer: StopServer,
  getServerStatus: GetServerStatus,
  listNodes: ListNodes,
}
