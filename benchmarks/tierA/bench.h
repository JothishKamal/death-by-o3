#ifndef BENCH_H
#define BENCH_H
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <stdint.h>

#define TRIALS 7

/* Opaque accumulators. Seeding each repetition's accumulator from a *volatile*
   makes every repetition genuinely data-dependent on the previous one, so LLVM
   can neither hoist the kernel out of the repetition loop nor CSE identical
   trials against each other. Values stay fully deterministic, so the printed
   CHECK remains a valid cross-variant output check.

   Without this, six of seven timing regions measured empty. */
static volatile double    g_d = 0.0;
static volatile long long g_i = 0;

static inline double now_s(void) {
  struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
  return (double)ts.tv_sec + 1e-9 * (double)ts.tv_nsec;
}

static inline uint32_t rnd32(uint64_t *s) {          /* xorshift64 */
  uint64_t x = *s; x ^= x << 13; x ^= x >> 7; x ^= x << 17; *s = x;
  return (uint32_t)(x >> 32);
}

static inline double rndf(uint64_t *s) {
  return (double)(rnd32(s) & 0xffff) / 65536.0 - 0.5;
}

static void report(double best, long reps, double checksum) {
  double ns = best * 1e9 / (double)reps;
  if (ns < 0.05) {
    fprintf(stderr, "FATAL: kernel optimised away (%g ns/rep)\n", ns);
    exit(3);
  }
  printf("NS_PER_REP %.4f\nCHECK %.10g\n", ns, checksum);
}
#endif
