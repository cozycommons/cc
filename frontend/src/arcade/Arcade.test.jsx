import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import Arcade from './Arcade';
const shared=vi.hoisted(()=>({session:{user:{id:'alice'},access_token:'test-access'},settings:{das_ms:200,arr_ms:35,keys:{left:'KeyJ',right:'KeyL',soft:'KeyK'},sound:true,opponent_level:0,frame_rate:60},bundle:{installed:true,can_install:false}}));
vi.mock('../contexts/SupabaseContext',()=>({useSupabase:()=>({supabase:{
 auth:{getSession:async()=>({data:{session:shared.session}}),
 onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}}), signInWithOAuth:vi.fn()}
}})}));
vi.mock('../api',()=>({getUrl:()=> 'http://localhost:8000'}));
beforeEach(()=>{
 shared.bundle={installed:true,can_install:false};
 shared.session={user:{id:'alice'},access_token:'test-access'};
 vi.stubGlobal('fetch',vi.fn(async(url,options={})=>({ok:true,json:async()=>{
  if(url.endsWith('/runs'))return [];
  if(url.endsWith('/package')) {if(options.method==='POST')shared.bundle={installed:true,can_install:true};return shared.bundle;}
  if(url.endsWith('/sessions'))return {id:'launch-1'};
  if(options.method==='PUT')return JSON.parse(options.body);
  return shared.settings;
 }})));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('loads server settings and saves the selected handling values',async()=>{
 render(<Arcade/>);
 const das=await screen.findByLabelText('DAS');
 expect(das.value).toBe('200');
 expect(screen.getByLabelText('Frame rate').value).toBe('60');
 fireEvent.change(das,{target:{value:'150'}});
 fireEvent.click(screen.getByRole('button',{name:'Save settings'}));
 await screen.findByText('Saved');
 const save=fetch.mock.calls.find(([,options])=>options.method==='PUT');
 expect(JSON.parse(save[1].body).das_ms).toBe(150);
 expect(save[1].headers.Authorization).toBe('Bearer test-access');
});
it('saves settings before creating an isolated game frame',async()=>{
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 await waitFor(()=>expect(screen.getByTitle('Sprint game')).toBeInTheDocument());
 expect(screen.getByTitle('Sprint game').src).toBe('http://localhost:8000/arcade/frame');
 expect(fetch.mock.calls.filter(([,options])=>options.method!=='GET').map(([url])=>url.split('/').pop())).toEqual(['profile','sessions']);
});

it('lets a Commons admin import a package before enabling play',async()=>{
 shared.bundle={installed:false,can_install:true};
 render(<Arcade/>);
 const upload=await screen.findByLabelText('Install game package');
 expect(screen.getByRole('button',{name:'Play'})).toBeDisabled();
 const file=new File(['private package'],'game.tar.gz',{type:'application/gzip'});
 fireEvent.change(upload,{target:{files:[file]}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'Play'})).toBeEnabled());
 const call=fetch.mock.calls.find(([url,options])=>url.endsWith('/package')&&options.method==='POST');
 expect(call[1].body).toBe(file);
 expect(call[1].headers.Authorization).toBe('Bearer test-access');
});
