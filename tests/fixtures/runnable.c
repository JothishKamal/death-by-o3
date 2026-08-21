#include <stdio.h>
#define N 96
static double A[N][N], B[N][N], C[N][N];
int main(void) {
  for (int i = 0; i < N; i++)
    for (int j = 0; j < N; j++) { A[i][j] = (i * 7 + j) % 13; B[i][j] = (i + j * 3) % 11; }
  for (int i = 0; i < N; i++)
    for (int k = 0; k < N; k++)
      for (int j = 0; j < N; j++) C[i][j] += A[i][k] * B[k][j];
  double s = 0.0;
  for (int i = 0; i < N; i++) s += C[i][i];
  printf("CHECK %.6f\n", s);
  return 0;
}
