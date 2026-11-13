/* Timer-source delivery for serial dispatch queues. Included by gcd.c.
 *
 * A timer thread decides when an event is due; it must not run that event
 * concurrently with another source targeting the same serial queue. Keep a
 * FIFO and one persistent guest-calling thread per serial queue. Besides
 * ordering, this avoids allocating an emulated guest stack for every timer.
 *
 * The timer waits for delivery, keeping its source and callback context alive
 * until the callback returns. Cancellation cleanup uses the same queue after
 * event delivery has finished. These queues live for the host process, as the
 * existing queue handles do. The modern host also uses the FIFO for general
 * dispatch work; asynchronous blocks are retained until their worker finishes.
 */
typedef struct source_job {
    struct source_job *next;
    dsource *source;
    void (__cdecl *fn)(void *);
    void *ctx;
    int cleanup;
    HANDLE done;
#ifdef TIGER_GUEST_64
    void *block;
    int asynchronous;
#endif
} source_job;

typedef struct {
    CRITICAL_SECTION lock;
    int serial;
    HANDLE wake, thread;
    source_job *head, *tail;
#ifdef TIGER_GUEST_64
    DWORD worker_id;
#endif
} source_queue;

static source_queue g_source_queues[64];

static source_queue *source_queue_of(void *handle)
{
    uintptr_t p = (uintptr_t)handle, base = (uintptr_t)g_dispatch_handles;
    if (p < base || p - base >= sizeof(int) * 64 || (p - base) % sizeof(int))
        return NULL;
    return &g_source_queues[(p - base) / sizeof(int)];
}

static void source_job_run(source_job *job)
{
#ifdef TIGER_GUEST_64
    if (!job->source) {
        if (job->block) block_invoke(job->block);
        else enter_engine(job->fn, job->ctx);
        return;
    }
#endif
    /* A cancelled event waiting behind another source must not run. Cleanup
     * still runs, including when the source cancelled itself in its handler. */
    if (job->cleanup || job->source->running) {
        enter_engine(job->fn, job->ctx);
        if (!job->cleanup) job->source->fired++;
    }
}

static DWORD WINAPI source_queue_thread(LPVOID arg)
{
    source_queue *q = (source_queue *)arg;
#ifdef TIGER_GUEST_64
    q->worker_id = GetCurrentThreadId();
#endif
    for (;;) {
        source_job *job;
        WaitForSingleObject(q->wake, INFINITE);
        for (;;) {
            EnterCriticalSection(&q->lock);
            job = q->head;
            if (job) {
                q->head = job->next;
                if (!q->head) q->tail = NULL;
            }
            LeaveCriticalSection(&q->lock);
            if (!job) break;
            source_job_run(job);
#ifdef TIGER_GUEST_64
            if (!job->source) {
                sh_Block_release(job->block);
                InterlockedDecrement(&g_dispatch_inflight);
                if (job->asynchronous) {
                    free(job);
                    continue;
                }
            }
#endif
            /* The waiting timer owns job; do not touch it after signalling. */
            SetEvent(job->done);
        }
    }
    return 0;
}

#ifdef TIGER_GUEST_64
static void modern_queue_submit(void *handle, void *block,
                                void (__cdecl *fn)(void *), void *ctx, int wait)
{
    source_queue *queue = source_queue_of(handle);
    if (!queue || !queue->serial) die("invalid modern dispatch queue");
    if (wait && queue->worker_id == GetCurrentThreadId()) {
        if (block) block_invoke(block);
        else enter_engine(fn, ctx);
        return;
    }
    source_job synchronous = {0};
    source_job *job = wait ? &synchronous : calloc(1, sizeof(*job));
    if (!job) die("cannot allocate queued speech work");
    job->fn = fn;
    job->ctx = ctx;
    job->asynchronous = !wait;
    job->block = block ? sh_Block_copy(block) : NULL;
    if (block && !job->block) die("cannot retain queued speech block");
    if (wait) {
        job->done = CreateEvent(NULL, FALSE, FALSE, NULL);
        if (!job->done) die("cannot create queued speech completion event");
    }
    InterlockedIncrement(&g_dispatch_inflight);
    EnterCriticalSection(&queue->lock);
    if (queue->tail) queue->tail->next = job;
    else queue->head = job;
    queue->tail = job;
    LeaveCriticalSection(&queue->lock);
    SetEvent(queue->wake);
    if (wait) {
        WaitForSingleObject(job->done, INFINITE);
        CloseHandle(job->done);
    }
}
#endif

static void source_queue_init(void *handle)
{
    source_queue *q = source_queue_of(handle);
    if (!q) die("invalid serial dispatch queue handle");
    InitializeCriticalSection(&q->lock);
    q->serial = 1;
    q->wake = CreateEvent(NULL, FALSE, FALSE, NULL);
    if (!q->wake) die("cannot create serial dispatch queue event");
    q->thread = CreateThread(NULL, 0, source_queue_thread, q, 0, NULL);
    if (!q->thread) die("cannot create serial dispatch queue worker");
}

static void source_deliver(dsource *s, void (__cdecl *fn)(void *), void *ctx,
                           int cleanup)
{
    source_queue *q = source_queue_of(s->queue);
    source_job job = {0};
    InterlockedIncrement(&g_dispatch_inflight);
    job.source = s; job.fn = fn; job.ctx = ctx; job.cleanup = cleanup;
    if (!q || !q->serial) {
        source_job_run(&job);
        InterlockedDecrement(&g_dispatch_inflight);
        return;
    }
    job.done = CreateEvent(NULL, FALSE, FALSE, NULL);
    if (!job.done) die("cannot create dispatch delivery event");
    EnterCriticalSection(&q->lock);
    if (q->tail) q->tail->next = &job;
    else q->head = &job;
    q->tail = &job;
    LeaveCriticalSection(&q->lock);
    SetEvent(q->wake);
    WaitForSingleObject(job.done, INFINITE);
    CloseHandle(job.done);
    InterlockedDecrement(&g_dispatch_inflight);
}
