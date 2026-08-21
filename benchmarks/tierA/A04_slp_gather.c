/* A04  slp-vectorizer.  Four values come from four unrelated arrays at four
   unrelated (gathered) indices. SLP still forms a <4 x float>: four
   insertelements in, one vector FMA, then extractelements back out. The
   build/tear-down shuffles cost more than the scalar ops they replace.
   Measured 1.29x at baseline SSE2; NEUTRAL at -march=native, where SLP
   re-costs and declines. ISA is a first-class axis. */
#include "bench.h"
#define N 4096
static float A[N], B[N], C[N], D[N];
static int i0[N], i1[N], i2[N], i3[N];

__attribute__((noinline))
static float gather4(int k, float seed) {
  float t0 = A[i0[k]], t1 = B[i1[k]], t2 = C[i2[k]], t3 = D[i3[k]];
  float r0 = t0 * 1.5f + seed, r1 = t1 * 1.5f + seed;
  float r2 = t2 * 1.5f + seed, r3 = t3 * 1.5f + seed;
  return r0 * r1 + r2 * r3;
}

int main(void) {
  uint64_t st = 7;
  for (int i = 0; i < N; i++) {
    A[i] = (float)rndf(&st); B[i] = (float)rndf(&st);
    C[i] = (float)rndf(&st); D[i] = (float)rndf(&st);
    i0[i] = (int)(rnd32(&st) % N); i1[i] = (int)(rnd32(&st) % N);
    i2[i] = (int)(rnd32(&st) % N); i3[i] = (int)(rnd32(&st) % N);
  }
  const int REPS = 400;
  double best = 1e30;
  for (int t = 0; t < TRIALS; t++) {
    double t0 = now_s();
    for (int r = 0; r < REPS; r++) {
      float a = (float)g_d;
      for (int k = 0; k < N; k++) a = 0.5f * a + gather4(k, a * 0.001f);
      g_d = a;
    }
    double t1 = now_s();
    if (t1 - t0 < best) best = t1 - t0;
  }
  report(best, (long)REPS * N, g_d);
  return 0;
}
