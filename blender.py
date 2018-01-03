import bpy
import arm.props_renderpath
import arm.material.make_shader
import arm.material.mat_state
import arm.material.cycles
import arm.material.make_mesh
import arm.make_renderpath
import arm.assets as assets
import arm.utils

def register():
    arm.props_renderpath.add_driver('Celshade', draw_props)
    arm.material.make_shader.make_rpass = make_rpass
    arm.make_renderpath.make_hook = make_rpath

def draw_props(layout):
    wrd = bpy.data.worlds['Arm']
    rpdat = arm.utils.get_rp()

    layout.prop(rpdat, "rp_shadowmap")
    if rpdat.rp_shadowmap != 'Off':
        layout.prop(rpdat, "rp_shadowmap_cascades")
    layout.prop(rpdat, "rp_background")
    layout.prop(rpdat, "rp_hdr")
    layout.prop(rpdat, "rp_stereo")
    layout.separator()
    layout.prop(rpdat, "rp_render_to_texture")
    if rpdat.rp_render_to_texture:
        layout.prop(rpdat, "rp_supersampling")
        layout.prop(rpdat, "rp_antialiasing")
        layout.prop(rpdat, "rp_compositornodes")
    layout.prop(rpdat, 'arm_samples_per_pixel')
    layout.prop(rpdat, 'arm_texture_filter')

def make_rpass(rpass):
    if rpass == 'mesh':
        return make_mesh(rpass)
    return None

def make_mesh(rpass):
    con = { 'name': rpass, 'depth_write': True, 'compare_mode': 'less', 'cull_mode': 'clockwise' }
    
    con_mesh = arm.material.mat_state.data.add_context(con)
    arm.material.mat_state.con_mesh = con_mesh

    wrd = bpy.data.worlds['Arm']
    vert = con_mesh.make_vert()
    frag = con_mesh.make_frag()
    geom = None
    tesc = None
    tese = None

    vert.add_uniform('mat3 N', '_normalMatrix')
    vert.write_main_header('vec4 spos = vec4(pos, 1.0);')
    frag.ins = vert.outs
    vert.add_uniform('mat4 WVP', '_worldViewProjectionMatrix')
    vert.write('gl_Position = WVP * spos;')

    frag.add_include('compiled.glsl')
    frag.add_uniform('vec3 lightDir', '_lampDirection')
    frag.add_uniform('vec3 lightColor', '_lampColor')

    frag.write('float visibility = 1.0;')
    frag.write('float dotNL = max(dot(n, lightDir), 0.0);')

    is_shadows = not '_NoShadows' in wrd.world_defs

    if is_shadows:
        vert.add_out('vec4 lampPos')
        vert.add_uniform('mat4 LWVP', '_biasLampWorldViewProjectionMatrix')
        vert.write('lampPos = LWVP * spos;')
        frag.add_include('std/shadows.glsl')
        frag.add_uniform('sampler2D shadowMap', included=True)
        frag.add_uniform('float shadowsBias', '_lampShadowsBias')
        frag.write('    if (lampPos.w > 0.0) {')
        frag.write('    vec3 lPos = lampPos.xyz / lampPos.w;')
        frag.write('    const float texelSize = 1.0 / shadowmapSize.x;')
        frag.write('    visibility = 0.0;')
        # TODO: CSM
        frag.write('    visibility += float(texture(shadowMap, lPos.xy).r + shadowsBias > lPos.z);')
        frag.write('    visibility += float(texture(shadowMap, lPos.xy + vec2(texelSize, 0.0)).r + shadowsBias > lPos.z) * 0.5;')
        frag.write('    visibility += float(texture(shadowMap, lPos.xy + vec2(-texelSize, 0.0)).r + shadowsBias > lPos.z) * 0.25;')
        frag.write('    visibility += float(texture(shadowMap, lPos.xy + vec2(0.0, texelSize)).r + shadowsBias > lPos.z) * 0.5;')
        frag.write('    visibility += float(texture(shadowMap, lPos.xy + vec2(0.0, -texelSize)).r + shadowsBias > lPos.z) * 0.25;')
        frag.write('    visibility /= 2.5;')
        frag.write('    visibility = max(visibility, 0.5);')
        # frag.write('    visibility = max(float(texture(shadowMap, lPos.xy).r + shadowsBias > lPos.z), 0.5);')
        frag.write('    }')

    frag.write('vec3 basecol;')
    frag.write('float roughness;')
    frag.write('float metallic;')
    frag.write('float occlusion;')
    arm_discard = arm.material.mat_state.material.arm_discard
    if arm_discard:
        frag.write('float opacity;')
    arm.material.cycles.parse(arm.material.mat_state.nodes, con_mesh, vert, frag, geom, tesc, tese, parse_opacity=arm_discard, parse_displacement=False)

    if arm_discard:
        opac = arm.material.mat_state.material.arm_discard_opacity
        frag.write('if (opacity < {0}) discard;'.format(opac))

    if con_mesh.is_elem('tex'):
        vert.add_out('vec2 texCoord')
        vert.write('texCoord = tex;')

    if con_mesh.is_elem('col'):
        vert.add_out('vec3 vcolor')
        vert.write('vcolor = col;')

    if con_mesh.is_elem('tang'):
        vert.add_out('mat3 TBN')
        arm.material.make_mesh.write_norpos(con_mesh, vert, declare=True)
        vert.write('vec3 tangent = normalize(N * tang);')
        vert.write('vec3 bitangent = normalize(cross(wnormal, tangent));')
        vert.write('TBN = mat3(tangent, bitangent, wnormal);')
    else:
        vert.add_out('vec3 wnormal')
        arm.material.make_mesh.write_norpos(con_mesh, vert)
        frag.prepend_header('vec3 n = normalize(wnormal);')

    frag.add_out('vec4 fragColor')
    frag.write('fragColor = vec4(basecol * max(step(0.5, dotNL), 0.3) * visibility * lightColor, 1.0);')

    if '_LDR' in wrd.world_defs:
        frag.write('fragColor.rgb = pow(fragColor.rgb, vec3(1.0 / 2.2));')

    assets.vs_equal(con_mesh, assets.shader_cons['mesh_vert'])

    arm.material.make_mesh.make_finalize(con_mesh)

    return con_mesh

def make_rpath():
    assets_path = arm.utils.get_sdk_path() + 'armory/Assets/'
    wrd = bpy.data.worlds['Arm']
    rpdat = arm.utils.get_rp()

    if rpdat.rp_shadowmap != 'Off':
        assets.add_khafile_def('rp_shadowmap')
        assets.add_khafile_def('rp_shadowmap_size={0}'.format(rpdat.rp_shadowmap))

    assets.add_khafile_def('rp_background={0}'.format(rpdat.rp_background))
    if rpdat.rp_background == 'World':
        assets.add_shader_pass('world_pass')

    if rpdat.rp_render_to_texture:
        assets.add_khafile_def('rp_render_to_texture')

        if rpdat.rp_compositornodes:
            assets.add_khafile_def('rp_compositornodes')
            compo_depth = False
            if wrd.arm_tonemap != 'Off':
                wrd.compo_defs = '_CTone' + wrd.arm_tonemap
            if rpdat.rp_antialiasing == 'FXAA':
                wrd.compo_defs += '_CFXAA'
            if wrd.arm_letterbox:
                wrd.compo_defs += '_CLetterbox'
            if wrd.arm_grain:
                wrd.compo_defs += '_CGrain'
            if bpy.data.scenes[0].cycles.film_exposure != 1.0:
                wrd.compo_defs += '_CExposure'
            if wrd.arm_fog:
                wrd.compo_defs += '_CFog'
                compo_depth = True
            if len(bpy.data.cameras) > 0 and bpy.data.cameras[0].dof_distance > 0.0:
                wrd.compo_defs += '_CDOF'
                compo_depth = True
            if compo_depth:
                wrd.compo_defs += '_CDepth'
                assets.add_khafile_def('rp_compositordepth')
            if wrd.arm_lens_texture != '':
                wrd.compo_defs += '_CLensTex'
                assets.add_embedded_data('lenstexture.jpg')
            if wrd.arm_fisheye:
                wrd.compo_defs += '_CFishEye'
            if wrd.arm_vignette:
                wrd.compo_defs += '_CVignette'
            if wrd.arm_lensflare:
                wrd.compo_defs += '_CGlare'
            if wrd.arm_lut_texture != '':
                wrd.compo_defs += '_CLUT'
                assets.add_embedded_data('luttexture.jpg')
            assets.add_shader_pass('compositor_pass')
        else:
            assets.add_shader_pass('copy_pass')

        assets.add_khafile_def('rp_antialiasing={0}'.format(rpdat.rp_antialiasing))

        if rpdat.rp_antialiasing == 'SMAA' or rpdat.rp_antialiasing == 'TAA':
            assets.add_shader_pass('smaa_edge_detect')
            assets.add_shader_pass('smaa_blend_weight')
            assets.add_shader_pass('smaa_neighborhood_blend')
            assets.add(assets_path + 'smaa_area.png')
            assets.add(assets_path + 'smaa_search.png')
            assets.add_embedded_data('smaa_area.png')
            assets.add_embedded_data('smaa_search.png')
            wrd.world_defs += '_SMAA'
            if rpdat.rp_antialiasing == 'TAA':
                assets.add_shader_pass('taa_pass')
                assets.add_shader_pass('copy_pass')

        if rpdat.rp_antialiasing == 'TAA' or rpdat.rp_motionblur == 'Object':
            assets.add_khafile_def('arm_veloc')
            wrd.world_defs += '_Veloc'
            if rpdat.rp_antialiasing == 'TAA':
                assets.add_khafile_def('arm_taa')

        assets.add_khafile_def('rp_supersampling={0}'.format(rpdat.rp_supersampling))        
        if rpdat.rp_supersampling == '4':
            assets.add_shader_pass('supersample_resolve')
