import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ProjectIntake from '@/components/ProjectIntake.vue'
import { stubFetch } from './helpers'
afterEach(()=>vi.unstubAllGlobals())

const intake={answer_limit:1200,total_answer_limit:6000,questions:[
  {id:'lessons',label:'Number of lessons',prompt:'Number of lessons',type:'integer',min:1,max:12,default:3,required:false},
  {id:'level',label:'Reading level',prompt:'Reading level',type:'choice',options:['grade 6-8','adult'],required:true},
  {id:'pictures',label:'Illustrations',prompt:'Illustrations',type:'boolean',default:false,required:false},
  {id:'subject',label:'Subject',prompt:'What is it about?',type:'text',max:200,required:true},
  {id:'audience',label:'Who is it for?',prompt:'Who will use it?',required:false}]}

it('shows template settings as controls with only allowed values, and drops values the template does not allow',async()=>{
  stubFetch(()=>({body:intake}))
  const w=mount(ProjectIntake,{props:{projectType:'demo',modelValue:{lessons:'40',level:'adult',subject:'Forces'}}})
  await flushPromises()
  expect(w.emitted('update:modelValue')!.at(-1)![0]).toEqual({level:'adult',subject:'Forces'})   // 40 is outside 1 to 12
  const box=w.get('fieldset.settings')
  expect(box.get('input[type="number"]').attributes()).toMatchObject({min:'1',max:'12'})
  expect(box.findAll('option').map(o=>o.text())).toEqual(['grade 6-8','adult'])
  await w.setProps({modelValue:{subject:'Forces'}})
  await box.get('input[type="checkbox"]').setValue(true)
  expect(w.emitted('update:modelValue')!.at(-1)![0]).toEqual({subject:'Forces',pictures:'yes'})
  expect(w.get('textarea').attributes('maxlength')).toBe('200')
})

it('is not ready until a required setting without a default is chosen',async()=>{
  stubFetch(()=>({body:intake}))
  const w=mount(ProjectIntake,{props:{projectType:'demo',modelValue:{subject:'Forces'}}})
  await flushPromises()
  expect(w.emitted('ready')!.at(-1)![0]).toBe(false)
  await w.setProps({modelValue:{subject:'Forces',level:'adult'}})
  expect(w.emitted('ready')!.at(-1)![0]).toBe(true)
})
