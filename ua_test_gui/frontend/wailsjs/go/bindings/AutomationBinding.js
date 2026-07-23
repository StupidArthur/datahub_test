// AutomationBinding.js - 由 wails generate module 自动生成;
// 这里手写以便 build 时类型/运行时都可解析。
import {automation} from '../models';

export function ListTestCases() {
  return window['go'].automation.AutomationBinding.ListTestCases();
}

export function RefreshTestCatalog() {
  return window['go'].automation.AutomationBinding.RefreshTestCatalog();
}

export function StartTestRun(arg1) {
  return window['go'].automation.AutomationBinding.StartTestRun(arg1);
}

export function StopTestRun(arg1) {
  return window['go'].automation.AutomationBinding.StopTestRun(arg1);
}

export function GetActiveTestRun() {
  return window['go'].automation.AutomationBinding.GetActiveTestRun();
}

export function ListTestRuns(arg1) {
  return window['go'].automation.AutomationBinding.ListTestRuns(arg1);
}

export function GetTestRunDetail(arg1) {
  return window['go'].automation.AutomationBinding.GetTestRunDetail(arg1);
}

export function GetRunEvents(arg1) {
  return window['go'].automation.AutomationBinding.GetRunEvents(arg1);
}

export function ReadRunLog(arg1) {
  return window['go'].automation.AutomationBinding.ReadRunLog(arg1);
}

export function OpenRunDirectory(arg1) {
  return window['go'].automation.AutomationBinding.OpenRunDirectory(arg1);
}