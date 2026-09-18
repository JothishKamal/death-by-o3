/* Enough simultaneously-live doubles to force the allocator to spill. */
double pressure(const double *p, int n) {
  double a0=0,a1=0,a2=0,a3=0,a4=0,a5=0,a6=0,a7=0;
  double b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0,b7=0;
  for (int i = 0; i < n; i++) {
    double v = p[i];
    a0+=v*1.1; a1+=v*1.2; a2+=v*1.3; a3+=v*1.4;
    a4+=v*1.5; a5+=v*1.6; a6+=v*1.7; a7+=v*1.8;
    b0+=a0*a1; b1+=a2*a3; b2+=a4*a5; b3+=a6*a7;
    b4+=b0*b1; b5+=b2*b3; b6+=b4*b5; b7+=b6*a0;
  }
  return a0+a1+a2+a3+a4+a5+a6+a7+b0+b1+b2+b3+b4+b5+b6+b7;
}
