  // Add body class so base.html styles adapt for full-screen shader
  document.body.classList.add('shader-page');

  (() => {
    const canvas = document.getElementById('shader-canvas');
    if (!canvas) return;

    const gl = canvas.getContext('webgl2');
    if (!gl) return;

    const vertexSrc = `#version 300 es
precision highp float;
in vec4 position;
void main(){gl_Position=position;}`;

    const fragmentSrc = `#version 300 es
precision highp float;
out vec4 O;
uniform vec2 resolution;
uniform float time;
uniform vec2 touch;
uniform int pointerCount;
#define FC gl_FragCoord.xy
#define T time
#define R resolution
#define MN min(R.x,R.y)

float rnd(vec2 p) {
  p=fract(p*vec2(12.9898,78.233));
  p+=dot(p,p+34.56);
  return fract(p.x*p.y);
}

float noise(in vec2 p) {
  vec2 i=floor(p), f=fract(p), u=f*f*(3.-2.*f);
  float
  a=rnd(i),
  b=rnd(i+vec2(1,0)),
  c=rnd(i+vec2(0,1)),
  d=rnd(i+1.);
  return mix(mix(a,b,u.x),mix(c,d,u.x),u.y);
}

float fbm(vec2 p) {
  float t=.0, a=1.; mat2 m=mat2(1.,-.5,.2,1.2);
  for (int i=0; i<5; i++) {
    t+=a*noise(p);
    p*=2.*m;
    a*=.5;
  }
  return t;
}

float clouds(vec2 p) {
  float d=1., t=.0;
  for (float i=.0; i<3.; i++) {
    float a=d*fbm(i*10.+p.x*.2+.2*(1.+i)*p.y+d+i*i+p);
    t=mix(t,d,a);
    d=a;
    p*=2./(i+1.);
  }
  return t;
}

void main(void) {
  vec2 uv=(FC-.5*R)/MN, st=uv*vec2(2,1);
  vec3 col=vec3(0);
  float bg=clouds(vec2(st.x+T*.5,-st.y));
  uv*=1.-.3*(sin(T*.2)*.5+.5);
  for (float i=1.; i<12.; i++) {
    uv+=.1*cos(i*vec2(.1+.01*i, .8)+i*i+T*.5+.1*uv.x);
    vec2 p=uv;
    float d=length(p);
    col+=.00125/d*(cos(sin(i)*vec3(2.2,2.8,3.8))+1.);
    float b=noise(i+p+bg*1.731);
    col+=.002*b/length(max(p,vec2(b*p.x*.02,p.y)));
    col=mix(col,vec3(bg*.06,bg*.08,bg*.22),d);
  }
  O=vec4(col,1);
}`;

    let program, vs, fs, buffer;
    const vertices = [-1, 1, -1, -1, 1, 1, 1, -1];
    let mouseCoords = [0, 0], nbrPointers = 0;

    function compile(shader, source) {
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error('Shader error:', gl.getShaderInfoLog(shader));
      }
    }

    function setup() {
      vs = gl.createShader(gl.VERTEX_SHADER);
      fs = gl.createShader(gl.FRAGMENT_SHADER);
      compile(vs, vertexSrc);
      compile(fs, fragmentSrc);
      program = gl.createProgram();
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        console.error(gl.getProgramInfoLog(program));
      }

      buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(vertices), gl.STATIC_DRAW);
      const pos = gl.getAttribLocation(program, 'position');
      gl.enableVertexAttribArray(pos);
      gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

      program._resolution = gl.getUniformLocation(program, 'resolution');
      program._time       = gl.getUniformLocation(program, 'time');
      program._touch      = gl.getUniformLocation(program, 'touch');
      program._pointerCount = gl.getUniformLocation(program, 'pointerCount');
    }

    function resize() {
      const dpr = Math.max(1, .5 * devicePixelRatio);
      canvas.width  = window.innerWidth  * dpr;
      canvas.height = window.innerHeight * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function render(now) {
      if (!program || gl.getProgramParameter(program, gl.DELETE_STATUS)) return;
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.uniform2f(program._resolution, canvas.width, canvas.height);
      gl.uniform1f(program._time, now * 1e-3);
      gl.uniform2f(program._touch, ...mouseCoords);
      gl.uniform1i(program._pointerCount, nbrPointers);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      requestAnimationFrame(render);
    }

    canvas.addEventListener('pointermove', (e) => {
      const dpr = Math.max(1, .5 * devicePixelRatio);
      mouseCoords = [e.clientX * dpr, canvas.height - e.clientY * dpr];
    });
    canvas.addEventListener('pointerdown', () => { nbrPointers++; });
    canvas.addEventListener('pointerup',   () => { nbrPointers = Math.max(0, nbrPointers - 1); });
    canvas.addEventListener('pointerleave', () => { nbrPointers = 0; });

    window.addEventListener('resize', resize);
    resize();
    setup();
    render(0);
  })();
