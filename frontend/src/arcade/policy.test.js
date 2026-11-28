import {it,expect} from 'vitest';
import {contentSecurityPolicies} from '../../csp.js';
it('allows only the API player frame and keeps credential documents frame-free',()=>{
 const policies=contentSecurityPolicies('https://api.example.test','https://auth.example.test');
 expect(policies.general).toContain('frame-src https://api.example.test/arcade/frame;');
 expect(policies.general).not.toContain('wasm-unsafe-eval');
 expect(policies.credentials).toContain("frame-src 'none'");
 expect(policies.credentials).not.toContain('/arcade');
});
