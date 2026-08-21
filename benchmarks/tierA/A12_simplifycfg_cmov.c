/* A12  simplifycfg (two-entry PHI folding / speculation).  A perfectly
   predicted branch guards an update of a serial dependence chain. Folding it
   into a select forces BOTH arms to be evaluated and puts the multiply on the
   critical path every iteration; the branchy form retires the cheap arm in one
   cycle because the predictor is never wrong.
   Measured 4.99x, checksums byte-identical across variants. */
#include "bench.h"
#define N 65536
static unsigned char c[N];

__attribute__((noinline))
static unsigned chain(const unsigned char *cc, int n, unsigned x) {
  for (int i = 0; i < n; i++) {
    if (cc[i]) x = x * 1103515245u + 12345u;   /* 3-cycle multiply */
    else       x = x + 7u;                     /* 1-cycle add      */
  }
  return x;
}

int main(void) {
  for (int i = 0; i < N; i++) c[i] = 0;   /* never taken -> always predicted */
  const int REPS = 60;
  double best = 1e30;
  for (int t = 0; t < TRIALS; t++) {
    double t0 = now_s();
    for (int r = 0; r < REPS; r++) { unsigned x = (unsigned)g_i; g_i = chain(c, N, x); }
    double t1 = now_s();
    if (t1 - t0 < best) best = t1 - t0;
  }
  report(best, (long)REPS * N, (double)(g_i & 0xffffff));
  return 0;
}
