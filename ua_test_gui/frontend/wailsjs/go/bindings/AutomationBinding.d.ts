// AutomationBinding.d.ts - 由 wails generate module 自动生成;
// 这里手写以保证 build 时类型可见(下次 wails build 会刷新)。
import {automation} from '../models';

export function ListTestCases(): Promise<automation.Catalog>;
export function RefreshTestCatalog(): Promise<automation.Catalog>;
export function StartTestRun(arg1: automation.StartRunRequest): Promise<automation.TestRun>;
export function StopTestRun(arg1: number): Promise<automation.TestRun>;
export function GetActiveTestRun(): Promise<automation.TestRun | null>;
export function ListTestRuns(arg1: automation.ListRunsRequest): Promise<automation.TestRun[]>;
export function GetTestRunDetail(arg1: number): Promise<automation.RunDetail>;
export function GetRunEvents(arg1: automation.GetEventsRequest): Promise<automation.TestEvent[]>;
export function ReadRunLog(arg1: automation.ReadLogRequest): Promise<automation.LogChunk>;
export function OpenRunDirectory(arg1: number): Promise<string>;