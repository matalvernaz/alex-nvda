// Supply the workloop and semaphore operations added by newer MacinTalk releases.
static int __cdecl modern_log_enabled(const void *log, unsigned char type) {
	// Apple's optional unified logger has no enabled destinations in this host; our own diagnostics go to NVDA's log.
	(void)log;
	(void)type;
	return 0;
}

static int __cdecl modern_condition_broadcast(cnd *condition) {
	if (!condition) { return 22; }
	cnd_ready(condition);
	WakeAllConditionVariable(cnd_native(condition));
	return 0;
}

static int __cdecl modern_condition_timedwait(cnd *condition, mtx *mutex, const int64_t *deadline) {
	if (!condition || !mutex || !deadline || deadline[0] < 0 || (uint64_t)deadline[0] > UINT64_MAX / 1000000000ULL || deadline[1] < 0 || deadline[1] >= 1000000000) { return 22; }
	uint64_t target = (uint64_t)deadline[0] * 1000000000ULL + deadline[1];
	uint64_t now = wall_us_scaled() * 1000ULL;
	// The engine reads our accelerated wall clock. Convert only its remaining
	// interval to a real wait, and release/reacquire the same native mutex.
	double remaining = target > now ? (double)(target - now) / g_speed / 1000000.0 : 0;
	DWORD wait = remaining >= INFINITE - 1 ? INFINITE - 1 : (DWORD)ceil(remaining);
	cnd_ready(condition);
	mtx_ready(mutex);
	return SleepConditionVariableCS(cnd_native(condition), mtx_native(mutex), wait) ? 0 : 60; // Darwin ETIMEDOUT.
}

static unsigned __cdecl modern_audio_component_count(const unsigned *description) {
	// AudioConverter is backed by the bundled Glint AAC decoder, so the engine need not register Apple's codec component.
	return description && description[0] == 0x61646563 && description[1] == 0x61616320 ? 1 : 0;
}

static void *__cdecl modern_workloop_create(const char *label) {
	return sh_dispatch_queue_create(label, NULL);
}

static void __cdecl modern_workloop_priority(void *queue, int priority, unsigned flags) {
	(void)queue;
	(void)priority;
	(void)flags;
}

static void __cdecl modern_dispatch_qos(void *queue, unsigned quality, int priority) {
	(void)queue;
	(void)quality;
	(void)priority;
}

static void *__cdecl modern_semaphore_create(glong value) {
	if (value < 0 || value > INT_MAX) { return NULL; }
	return CreateSemaphoreA(NULL, value, INT_MAX, NULL);
}

static glong __cdecl modern_semaphore_signal(void *semaphore) {
	if (!ReleaseSemaphore(semaphore, 1, NULL)) { die("cannot signal speech semaphore"); }
	return 0;
}

static glong __cdecl modern_semaphore_wait(void *semaphore, uint64_t deadline) {
	DWORD wait = INFINITE;
	if (deadline != UINT64_MAX && deadline != INT64_MAX) {
		uint64_t now = GetTickCount64() * 1000000ULL;
		uint64_t remaining = deadline > now ? (deadline - now + 999999) / 1000000 : 0;
		wait = remaining < INFINITE ? (DWORD)remaining : INFINITE - 1;
	}
	DWORD result = WaitForSingleObject(semaphore, wait);
	if (result == WAIT_OBJECT_0) { return 0; }
	if (result == WAIT_TIMEOUT) { return 1; }
	die("cannot wait for speech semaphore");
	return -1;
}

typedef struct {
	uint64_t deadline;
	void *queue;
	void *block;
} modern_after;

static DWORD WINAPI modern_after_thread(void *context) {
	modern_after *request = context;
	uint64_t now = GetTickCount64() * 1000000ULL;
	if (request->deadline > now) {
		uint64_t delay = (request->deadline - now + 999999) / 1000000;
		if (delay > 60000) { die("speech deferred work exceeded one minute"); }
		Sleep((DWORD)delay);
	}
	sh_dispatch_async(request->queue, request->block);
	sh_Block_release(request->block);
	free(request);
	return 0;
}

static void __cdecl modern_dispatch_after(uint64_t deadline, void *queue, void *block) {
	modern_after *request = malloc(sizeof(*request));
	if (!request) { die("cannot allocate deferred speech work"); }
	request->deadline = deadline;
	request->queue = queue;
	request->block = sh_Block_copy(block);
	HANDLE worker = CreateThread(NULL, 0, modern_after_thread, request, 0, NULL);
	if (!worker) { die("cannot start deferred speech worker"); }
	CloseHandle(worker);
}
