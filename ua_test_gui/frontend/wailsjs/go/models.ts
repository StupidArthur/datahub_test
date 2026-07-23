export namespace bindings {
	
	export class KillPortResult {
	    port: number;
	    ok: boolean;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new KillPortResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.port = source["port"];
	        this.ok = source["ok"];
	        this.msg = source["msg"];
	    }
	}
	export class LoginRequest {
	    baseUrl: string;
	    username: string;
	    password: string;
	    tenantId: string;
	    timeoutSec: number;
	
	    static createFrom(source: any = {}) {
	        return new LoginRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.baseUrl = source["baseUrl"];
	        this.username = source["username"];
	        this.password = source["password"];
	        this.tenantId = source["tenantId"];
	        this.timeoutSec = source["timeoutSec"];
	    }
	}
	export class LoginResult {
	    ok: boolean;
	    baseUrl: string;
	    tenantId: string;
	
	    static createFrom(source: any = {}) {
	        return new LoginResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ok = source["ok"];
	        this.baseUrl = source["baseUrl"];
	        this.tenantId = source["tenantId"];
	    }
	}
	export class MockStopResult {
	    key: string;
	    ok: boolean;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new MockStopResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.key = source["key"];
	        this.ok = source["ok"];
	        this.msg = source["msg"];
	    }
	}
	export class RunDetailResponse {
	    run: verify.RunRecord;
	    results: verify.VerifyTagResult[];
	
	    static createFrom(source: any = {}) {
	        return new RunDetailResponse(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run = this.convertValues(source["run"], verify.RunRecord);
	        this.results = this.convertValues(source["results"], verify.VerifyTagResult);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class SetMockerConfigRequest {
	    repo: string;
	    python: string;
	    exe: string;
	
	    static createFrom(source: any = {}) {
	        return new SetMockerConfigRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.repo = source["repo"];
	        this.python = source["python"];
	        this.exe = source["exe"];
	    }
	}
	export class StartAllResult {
	    started: string[];
	    mocks: mock.MockSummary[];
	
	    static createFrom(source: any = {}) {
	        return new StartAllResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.started = source["started"];
	        this.mocks = this.convertValues(source["mocks"], mock.MockSummary);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class StopAllResult {
	    stopped: string[];
	
	    static createFrom(source: any = {}) {
	        return new StopAllResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stopped = source["stopped"];
	    }
	}

}

export namespace env {
	
	export class PortStatus {
	    port: number;
	    inUse: boolean;
	    pid: number;
	    process: string;
	
	    static createFrom(source: any = {}) {
	        return new PortStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.port = source["port"];
	        this.inUse = source["inUse"];
	        this.pid = source["pid"];
	        this.process = source["process"];
	    }
	}
	export class EnvStatus {
	    ports: PortStatus[];
	    localIps: string[];
	    pickIp: string;
	    connectivityOk: boolean;
	    connectivityMsg: string;
	
	    static createFrom(source: any = {}) {
	        return new EnvStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ports = this.convertValues(source["ports"], PortStatus);
	        this.localIps = source["localIps"];
	        this.pickIp = source["pickIp"];
	        this.connectivityOk = source["connectivityOk"];
	        this.connectivityMsg = source["connectivityMsg"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace mock {
	
	export class UaNodeSpec {
	    Name: string;
	    Type: string;
	    Count: number;
	    Change: boolean;
	    Writable: boolean;
	    Default: any;
	
	    static createFrom(source: any = {}) {
	        return new UaNodeSpec(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Name = source["Name"];
	        this.Type = source["Type"];
	        this.Count = source["Count"];
	        this.Change = source["Change"];
	        this.Writable = source["Writable"];
	        this.Default = source["Default"];
	    }
	}
	export class MockSpec {
	    Key: string;
	    Name: string;
	    Port: number;
	    CycleMs: number;
	    Nodes: UaNodeSpec[];
	    HeartbeatTag: string;
	    Desc: string;
	
	    static createFrom(source: any = {}) {
	        return new MockSpec(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Key = source["Key"];
	        this.Name = source["Name"];
	        this.Port = source["Port"];
	        this.CycleMs = source["CycleMs"];
	        this.Nodes = this.convertValues(source["Nodes"], UaNodeSpec);
	        this.HeartbeatTag = source["HeartbeatTag"];
	        this.Desc = source["Desc"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class MockRuntime {
	    spec: MockSpec;
	    pid: number;
	    configPath: string;
	    logPath: string;
	    status: string;
	    reason: string;
	    endpoint: string;
	
	    static createFrom(source: any = {}) {
	        return new MockRuntime(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.spec = this.convertValues(source["spec"], MockSpec);
	        this.pid = source["pid"];
	        this.configPath = source["configPath"];
	        this.logPath = source["logPath"];
	        this.status = source["status"];
	        this.reason = source["reason"];
	        this.endpoint = source["endpoint"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class MockSummary {
	    key: string;
	    name: string;
	    port: number;
	    status: string;
	    endpoint: string;
	    nodeCount: number;
	
	    static createFrom(source: any = {}) {
	        return new MockSummary(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.key = source["key"];
	        this.name = source["name"];
	        this.port = source["port"];
	        this.status = source["status"];
	        this.endpoint = source["endpoint"];
	        this.nodeCount = source["nodeCount"];
	    }
	}
	export class MockerConfigResult {
	    repo: string;
	    python: string;
	    mainPy: string;
	    exe: string;
	    ok: boolean;
	    exeOk: boolean;
	
	    static createFrom(source: any = {}) {
	        return new MockerConfigResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.repo = source["repo"];
	        this.python = source["python"];
	        this.mainPy = source["mainPy"];
	        this.exe = source["exe"];
	        this.ok = source["ok"];
	        this.exeOk = source["exeOk"];
	    }
	}
	export class PerfParams {
	    pollN: number;
	    writeN: number;
	    ratio: number;
	
	    static createFrom(source: any = {}) {
	        return new PerfParams(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.pollN = source["pollN"];
	        this.writeN = source["writeN"];
	        this.ratio = source["ratio"];
	    }
	}
	export class TagSpec {
	    name: string;
	    mockerType: string;
	    writable: boolean;
	    frequency: number;
	
	    static createFrom(source: any = {}) {
	        return new TagSpec(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.mockerType = source["mockerType"];
	        this.writable = source["writable"];
	        this.frequency = source["frequency"];
	    }
	}

}

export namespace provision {
	
	export class AddDataSourceRequest {
	    dsName: string;
	    endpoint: string;
	
	    static createFrom(source: any = {}) {
	        return new AddDataSourceRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsName = source["dsName"];
	        this.endpoint = source["endpoint"];
	    }
	}
	export class AddMissingTagsRequest {
	    mockKey: string;
	    endpoint: string;
	    frequency: number;
	
	    static createFrom(source: any = {}) {
	        return new AddMissingTagsRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.endpoint = source["endpoint"];
	        this.frequency = source["frequency"];
	    }
	}
	export class ChangeDsStateRequest {
	    dsId: number;
	    enabled: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ChangeDsStateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	        this.enabled = source["enabled"];
	    }
	}
	export class DeleteAllTagsRequest {
	    dsId: number;
	
	    static createFrom(source: any = {}) {
	        return new DeleteAllTagsRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	    }
	}
	export class DeleteDataSourceRequest {
	    dsId: number;
	
	    static createFrom(source: any = {}) {
	        return new DeleteDataSourceRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	    }
	}
	export class DeleteDuplicateTagsRequest {
	    dsId: number;
	
	    static createFrom(source: any = {}) {
	        return new DeleteDuplicateTagsRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	    }
	}
	export class SmokeResult {
	    ok: boolean;
	    msg: string;
	    write: any;
	    readback: any;
	
	    static createFrom(source: any = {}) {
	        return new SmokeResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.ok = source["ok"];
	        this.msg = source["msg"];
	        this.write = source["write"];
	        this.readback = source["readback"];
	    }
	}
	export class TagFail {
	    name: string;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new TagFail(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.error = source["error"];
	    }
	}
	export class DsProvisionResult {
	    dsId: number;
	    dsReused: boolean;
	    dsAlive: boolean;
	    tagsAdded: string[];
	    tagsSkippedUnsupported: string[];
	    tagsFailed: TagFail[];
	    tagsDeleted: string[];
	    tagsDeleteMissing: string[];
	    smoke: SmokeResult;
	
	    static createFrom(source: any = {}) {
	        return new DsProvisionResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	        this.dsReused = source["dsReused"];
	        this.dsAlive = source["dsAlive"];
	        this.tagsAdded = source["tagsAdded"];
	        this.tagsSkippedUnsupported = source["tagsSkippedUnsupported"];
	        this.tagsFailed = this.convertValues(source["tagsFailed"], TagFail);
	        this.tagsDeleted = source["tagsDeleted"];
	        this.tagsDeleteMissing = source["tagsDeleteMissing"];
	        this.smoke = this.convertValues(source["smoke"], SmokeResult);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class DuplicateGroup {
	    tagName: string;
	    count: number;
	    ids: number[];
	
	    static createFrom(source: any = {}) {
	        return new DuplicateGroup(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tagName = source["tagName"];
	        this.count = source["count"];
	        this.ids = source["ids"];
	    }
	}
	export class GetHeartbeatValueRequest {
	    dsId: number;
	    tagName: string;
	
	    static createFrom(source: any = {}) {
	        return new GetHeartbeatValueRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	        this.tagName = source["tagName"];
	    }
	}
	export class HeartbeatValue {
	    tagName: string;
	    tagValue: any;
	    quality: number;
	    ok: boolean;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new HeartbeatValue(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tagName = source["tagName"];
	        this.tagValue = source["tagValue"];
	        this.quality = source["quality"];
	        this.ok = source["ok"];
	        this.msg = source["msg"];
	    }
	}
	export class ProvisionRequest {
	    mockKey: string;
	    dsName: string;
	    endpoint: string;
	    frequency: number;
	    smokeTag: string;
	    smokeSettleSec: number;
	    confirmDelete: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ProvisionRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.dsName = source["dsName"];
	        this.endpoint = source["endpoint"];
	        this.frequency = source["frequency"];
	        this.smokeTag = source["smokeTag"];
	        this.smokeSettleSec = source["smokeSettleSec"];
	        this.confirmDelete = source["confirmDelete"];
	    }
	}
	export class TagStatus {
	    name: string;
	    mockerType: string;
	    writable: boolean;
	    inDs: boolean;
	    duplicate: boolean;
	    duplicateCount: number;
	
	    static createFrom(source: any = {}) {
	        return new TagStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.mockerType = source["mockerType"];
	        this.writable = source["writable"];
	        this.inDs = source["inDs"];
	        this.duplicate = source["duplicate"];
	        this.duplicateCount = source["duplicateCount"];
	    }
	}
	export class ProvisionState {
	    mockKey: string;
	    endpoint: string;
	    heartbeatTag: string;
	    dsInfo?: subject.DsInfo;
	    dsAlive: boolean;
	    tagsInDsCount: number;
	    mockTags: mock.TagSpec[];
	    tagStatuses: TagStatus[];
	    missingTags: mock.TagSpec[];
	    duplicateTags: DuplicateGroup[];
	    unsupportedTags: mock.TagSpec[];
	
	    static createFrom(source: any = {}) {
	        return new ProvisionState(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.endpoint = source["endpoint"];
	        this.heartbeatTag = source["heartbeatTag"];
	        this.dsInfo = this.convertValues(source["dsInfo"], subject.DsInfo);
	        this.dsAlive = source["dsAlive"];
	        this.tagsInDsCount = source["tagsInDsCount"];
	        this.mockTags = this.convertValues(source["mockTags"], mock.TagSpec);
	        this.tagStatuses = this.convertValues(source["tagStatuses"], TagStatus);
	        this.missingTags = this.convertValues(source["missingTags"], mock.TagSpec);
	        this.duplicateTags = this.convertValues(source["duplicateTags"], DuplicateGroup);
	        this.unsupportedTags = this.convertValues(source["unsupportedTags"], mock.TagSpec);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class ProvisionStateRequest {
	    mockKey: string;
	    endpoint: string;
	    frequency: number;
	
	    static createFrom(source: any = {}) {
	        return new ProvisionStateRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.endpoint = source["endpoint"];
	        this.frequency = source["frequency"];
	    }
	}
	export class RebuildDataSourceRequest {
	    mockKey: string;
	    dsName: string;
	    endpoint: string;
	    frequency: number;
	
	    static createFrom(source: any = {}) {
	        return new RebuildDataSourceRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.dsName = source["dsName"];
	        this.endpoint = source["endpoint"];
	        this.frequency = source["frequency"];
	    }
	}
	
	

}

export namespace subject {
	
	export class DsInfo {
	    id: number;
	    name: string;
	    dsName: string;
	    dsType: number;
	    dsSubType: number;
	    dsTarUrl: string;
	    dsStatus: number;
	    alive: boolean;
	
	    static createFrom(source: any = {}) {
	        return new DsInfo(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.dsName = source["dsName"];
	        this.dsType = source["dsType"];
	        this.dsSubType = source["dsSubType"];
	        this.dsTarUrl = source["dsTarUrl"];
	        this.dsStatus = source["dsStatus"];
	        this.alive = source["alive"];
	    }
	}

}

export namespace verify {
	
	export class RunRecord {
	    id: number;
	    startedAt: string;
	    finishedAt: string;
	    status: string;
	    env: string;
	    mockKey: string;
	    total: number;
	    passed: number;
	    failed: number;
	    progress: number;
	
	    static createFrom(source: any = {}) {
	        return new RunRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.startedAt = source["startedAt"];
	        this.finishedAt = source["finishedAt"];
	        this.status = source["status"];
	        this.env = source["env"];
	        this.mockKey = source["mockKey"];
	        this.total = source["total"];
	        this.passed = source["passed"];
	        this.failed = source["failed"];
	        this.progress = source["progress"];
	    }
	}
	export class VerifyRequest {
	    mockKey: string;
	    endpoint: string;
	    namespaceIndex: number;
	    settleSec: number;
	    runId: number;
	
	    static createFrom(source: any = {}) {
	        return new VerifyRequest(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mockKey = source["mockKey"];
	        this.endpoint = source["endpoint"];
	        this.namespaceIndex = source["namespaceIndex"];
	        this.settleSec = source["settleSec"];
	        this.runId = source["runId"];
	    }
	}
	export class VerifyTagResult {
	    runId: number;
	    tagName: string;
	    type: string;
	    rtBefore: number[];
	    srcBefore: number[];
	    writeVal: number[];
	    rtAfter: number[];
	    ok: boolean;
	    msg: string;
	
	    static createFrom(source: any = {}) {
	        return new VerifyTagResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.runId = source["runId"];
	        this.tagName = source["tagName"];
	        this.type = source["type"];
	        this.rtBefore = source["rtBefore"];
	        this.srcBefore = source["srcBefore"];
	        this.writeVal = source["writeVal"];
	        this.rtAfter = source["rtAfter"];
	        this.ok = source["ok"];
	        this.msg = source["msg"];
	    }
	}
export class VerifyRunResult {
	    runId: number;
	    total: number;
	    passed: number;
	    failed: number;
	    results: VerifyTagResult[];

	    static createFrom(source: any = {}) {
	        return new VerifyRunResult(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.runId = source["runId"];
	        this.total = source["total"];
	        this.passed = source["passed"];
	        this.failed = source["failed"];
	        this.results = this.convertValues(source["results"], VerifyTagResult);
	    }

		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace automation {

	export class TestRun {
	    id: number;
	    runKey: string;
	    status: string;
	    createdAt: string;
	    startedAt: string;
	    finishedAt: string;
	    selectedCases: string[];
	    total: number;
	    progress: number;
	    passed: number;
	    failed: number;
	    errors: number;
	    skipped: number;
	    blocked: number;
	    observed: number;
	    measured: number;
	    cleanupFailed: number;
	    currentCaseId: string;
	    currentStep: string;
	    pid: number;
	    exitCode?: number;
	    runDir: string;
	    reportPath: string;
	    logPath: string;
	    errorMessage: string;
	    note: string;

	    static createFrom(source: any = {}) {
	        return new TestRun(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runKey = source["runKey"];
	        this.status = source["status"];
	        this.createdAt = source["createdAt"];
	        this.startedAt = source["startedAt"];
	        this.finishedAt = source["finishedAt"];
	        this.selectedCases = source["selectedCases"];
	        this.total = source["total"];
	        this.progress = source["progress"];
	        this.passed = source["passed"];
	        this.failed = source["failed"];
	        this.errors = source["errors"];
	        this.skipped = source["skipped"];
	        this.blocked = source["blocked"];
	        this.observed = source["observed"];
	        this.measured = source["measured"];
	        this.cleanupFailed = source["cleanupFailed"];
	        this.currentCaseId = source["currentCaseId"];
	        this.currentStep = source["currentStep"];
	        this.pid = source["pid"];
	        this.exitCode = source["exitCode"];
	        this.runDir = source["runDir"];
	        this.reportPath = source["reportPath"];
	        this.logPath = source["logPath"];
	        this.errorMessage = source["errorMessage"];
	        this.note = source["note"];
	    }
	}

	export class CaseResult {
	    id: number;
	    runId: number;
	    caseId: string;
	    title: string;
	    status: string;
	    startedAt: string;
	    finishedAt: string;
	    durationMs: number;
	    summary: string;
	    cleanupStatus: string;
	    cleanupMessage: string;

	    static createFrom(source: any = {}) {
	        return new CaseResult(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runId = source["runId"];
	        this.caseId = source["caseId"];
	        this.title = source["title"];
	        this.status = source["status"];
	        this.startedAt = source["startedAt"];
	        this.finishedAt = source["finishedAt"];
	        this.durationMs = source["durationMs"];
	        this.summary = source["summary"];
	        this.cleanupStatus = source["cleanupStatus"];
	        this.cleanupMessage = source["cleanupMessage"];
	    }
	}

	export class StepResult {
	    id: number;
	    runId: number;
	    caseId: string;
	    stepId: string;
	    title: string;
	    status: string;
	    startedAt: string;
	    finishedAt: string;
	    durationMs: number;
	    message: string;

	    static createFrom(source: any = {}) {
	        return new StepResult(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runId = source["runId"];
	        this.caseId = source["caseId"];
	        this.stepId = source["stepId"];
	        this.title = source["title"];
	        this.status = source["status"];
	        this.startedAt = source["startedAt"];
	        this.finishedAt = source["finishedAt"];
	        this.durationMs = source["durationMs"];
	        this.message = source["message"];
	    }
	}

	export class Metric {
	    id: number;
	    runId: number;
	    caseId: string;
	    name: string;
	    value?: number;
	    textValue: string;
	    unit: string;
	    labels: {[key: string]: string};

	    static createFrom(source: any = {}) {
	        return new Metric(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runId = source["runId"];
	        this.caseId = source["caseId"];
	        this.name = source["name"];
	        this.value = source["value"];
	        this.textValue = source["textValue"];
	        this.unit = source["unit"];
	        this.labels = source["labels"];
	    }
	}

	export class Evidence {
	    id: number;
	    runId: number;
	    caseId: string;
	    kind: string;
	    path: string;
	    title: string;
	    metadata: {[key: string]: any};

	    static createFrom(source: any = {}) {
	        return new Evidence(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runId = source["runId"];
	        this.caseId = source["caseId"];
	        this.kind = source["kind"];
	        this.path = source["path"];
	        this.title = source["title"];
	        this.metadata = source["metadata"];
	    }
	}

	export class TestEvent {
	    id: number;
	    runId: number;
	    eventType: string;
	    caseId: string;
	    payload: any;
	    ts: string;

	    static createFrom(source: any = {}) {
	        return new TestEvent(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.runId = source["runId"];
	        this.eventType = source["eventType"];
	        this.caseId = source["caseId"];
	        this.payload = source["payload"];
	        this.ts = source["ts"];
	    }
	}

	export class CaseStep {
	    stepId: string;
	    title: string;

	    static createFrom(source: any = {}) {
	        return new CaseStep(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.stepId = source["stepId"];
	        this.title = source["title"];
	    }
	}

	export class Case {
	    id: string;
	    title: string;
	    kind: string;
	    implemented: boolean;
	    tags: string[];
	    timeoutSec: number;
	    destructive: boolean;
	    exclusiveResources: string[];
	    docPath: string;
	    description: string;
	    steps: CaseStep[];
	    assertions: string[];

	    static createFrom(source: any = {}) {
	        return new Case(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.title = source["title"];
	        this.kind = source["kind"];
	        this.implemented = source["implemented"];
	        this.tags = source["tags"];
	        this.timeoutSec = source["timeoutSec"];
	        this.destructive = source["destructive"];
	        this.exclusiveResources = source["exclusiveResources"];
	        this.docPath = source["docPath"];
	        this.description = source["description"];
	        this.steps = this.convertValues(source["steps"], CaseStep);
	        this.assertions = source["assertions"];
	    }

		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

	export class Chapter {
	    id: string;
	    title: string;
	    cases: Case[];

	    static createFrom(source: any = {}) {
	        return new Chapter(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.title = source["title"];
	        this.cases = this.convertValues(source["cases"], Case);
	    }

		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

	export class Catalog {
	    version: number;
	    generatedAt: string;
	    chapters: Chapter[];

	    static createFrom(source: any = {}) {
	        return new Catalog(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.version = source["version"];
	        this.generatedAt = source["generatedAt"];
	        this.chapters = this.convertValues(source["chapters"], Chapter);
	    }

		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

	export class StartRunRequest {
	    selectedCaseIds: string[];
	    note: string;
	    allowPerformance: boolean;
	    runKey: string;

	    static createFrom(source: any = {}) {
	        return new StartRunRequest(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.selectedCaseIds = source["selectedCaseIds"];
	        this.note = source["note"];
	        this.allowPerformance = source["allowPerformance"];
	        this.runKey = source["runKey"];
	    }
	}

	export class ListRunsRequest {
	    limit: number;
	    status: string;
	    keyword: string;

	    static createFrom(source: any = {}) {
	        return new ListRunsRequest(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.limit = source["limit"];
	        this.status = source["status"];
	        this.keyword = source["keyword"];
	    }
	}

	export class RunDetail {
	    run: TestRun;
	    cases: CaseResult[];
	    events: TestEvent[];
	    metrics: Metric[];
	    evidence: Evidence[];

	    static createFrom(source: any = {}) {
	        return new RunDetail(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run = this.convertValues(source["run"], TestRun);
	        this.cases = this.convertValues(source["cases"], CaseResult);
	        this.events = this.convertValues(source["events"], TestEvent);
	        this.metrics = this.convertValues(source["metrics"], Metric);
	        this.evidence = this.convertValues(source["evidence"], Evidence);
	    }

		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

	export class GetEventsRequest {
	    runId: number;
	    afterId: number;
	    limit: number;

	    static createFrom(source: any = {}) {
	        return new GetEventsRequest(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.runId = source["runId"];
	        this.afterId = source["afterId"];
	        this.limit = source["limit"];
	    }
	}

	export class ReadLogRequest {
	    runId: number;
	    offset: number;
	    limit: number;

	    static createFrom(source: any = {}) {
	        return new ReadLogRequest(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.runId = source["runId"];
	        this.offset = source["offset"];
	        this.limit = source["limit"];
	    }
	}

	export class LogChunk {
	    runId: number;
	    offset: number;
	    next: number;
	    eof: boolean;
	    content: string;

	    static createFrom(source: any = {}) {
	        return new LogChunk(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.runId = source["runId"];
	        this.offset = source["offset"];
	        this.next = source["next"];
	        this.eof = source["eof"];
	        this.content = source["content"];
	    }
	}

}

