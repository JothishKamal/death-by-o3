#define NI 64
#define NJ 64
#define NK 64
void kernel_gemm(double alpha, double beta,
                 double C[NI][NJ], double A[NI][NK], double B[NK][NJ]) {
  for (int i = 0; i < NI; i++) {
    for (int j = 0; j < NJ; j++) C[i][j] *= beta;
    for (int k = 0; k < NK; k++)
      for (int j = 0; j < NJ; j++)
        C[i][j] += alpha * A[i][k] * B[k][j];
  }
}
static int helper(int x) { return x * 3 + 1; }
int recurse_a(int n);
int recurse_b(int n) { return n <= 0 ? 0 : recurse_a(n - 1) + helper(n); }
int recurse_a(int n) { return n <= 0 ? 1 : recurse_b(n - 1) + 2; }
